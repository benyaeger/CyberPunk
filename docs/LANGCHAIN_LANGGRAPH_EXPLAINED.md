# LangChain & LangGraph in CyberPunk — A Walkthrough

This document explains, in depth, how CyberPunk is built on top of the
`langchain-core`, `langchain-ollama`, and `langgraph` libraries. It's written
for someone new to the Lang\* ecosystem who wants to learn by reading a real
project instead of hello-world snippets.

We'll move top-down: **tools → model → graph → run loop → callbacks**. Every
section points at the exact file in the repo so you can follow along.

---

## 1. The mental model

LangChain and LangGraph solve two different problems:

- **LangChain** gives you *building blocks* — a unified interface for chat
  models (`BaseChatModel`), tools (`BaseTool`), messages (`HumanMessage`,
  `AIMessage`, `ToolMessage`, `SystemMessage`), and a cross-cutting
  observability hook (`BaseCallbackHandler`).
- **LangGraph** is a *runtime* that wires those blocks into a state machine.
  You define nodes (functions that read state and return a state update) and
  edges (which node runs next). LangGraph handles threading state through the
  graph, streaming intermediate updates, and stopping cleanly.

CyberPunk's agent is a classic **tool-calling loop**: the LLM sees a prompt,
decides whether to call a tool or answer, and if it calls a tool, the tool
result is fed back in until the model produces a final answer. LangGraph
expresses this as a two-node cycle — `agent ↔ tools` — with a hard cap to
force a summary if the model keeps calling tools forever.

---

## 2. Tools: the things the model can call

See [cyberpunk/tools/arp_scanner.py](cyberpunk/tools/arp_scanner.py) and
[cyberpunk/tools/__init__.py](cyberpunk/tools/__init__.py).

### The `@tool` decorator

A LangChain tool is just a Python function with a schema. The `@tool`
decorator wraps a function into a `StructuredTool` — a subclass of
`BaseTool`. LangChain introspects the function's **signature** (for the
argument schema) and its **docstring** (for the description shown to the
LLM).

```python
@tool
def get_arp_table() -> dict[str, Any]:
    """Read the local ARP cache to find known neighbor devices.

    Returns IP addresses, MAC addresses, and interface names...
    """
    ...
```

The decorator gives us four things for free:

1. A JSON Schema derived from the function signature, sent to the model as
   part of the tool definition.
2. A `name` (the function name) and `description` (the docstring).
3. A validated call site: when the LLM emits `{"name": "get_arp_table",
   "args": {}}`, LangChain/LangGraph will validate args against the schema
   before calling your function.
4. A `.invoke(kwargs)` method that unifies sync/async/batch execution.

### Tagging for stealth mode

LangChain `BaseTool`s carry a free-form `tags: list[str] | None`. CyberPunk
uses this to mark tools as `"passive"` / `"active"` / `"analysis"`:

```python
def _register(module: ModuleType, attr: str) -> BaseTool:
    tool: BaseTool = getattr(module, attr)
    tool.tags = [module.CATEGORY]
    return tool
```

Then `available_tools(stealth=True)` just filters the list:

```python
return [t for t in TOOLS if "active" not in (t.tags or [])]
```

**Lesson:** `tags` is the intended extension point for cross-cutting metadata.
You don't need to subclass `BaseTool` to attach a category — tag it.

### Wrapping tools per run

See [cyberpunk/agent/tool_wrapper.py](cyberpunk/agent/tool_wrapper.py).

We don't hand the raw tools to LangGraph. Instead we produce **wrapped** copies
for each run, adding:

- a per-run result cache (so the model can't burn an iteration re-calling the
  same tool with the same args),
- a second stealth check (defense in depth),
- timing, status-panel updates, and audit log writes.

The wrapper is built with `StructuredTool.from_function`, which is the
programmatic equivalent of `@tool`:

```python
return StructuredTool.from_function(
    func=_invoke,
    name=raw.name,
    description=raw.description,
    args_schema=raw.args_schema,   # carry the original schema through
    tags=raw.tags,                 # and the tags
)
```

An important detail: the wrapper returns a **string** (JSON for success,
`"Error: ..."` for failure). LangGraph's `ToolNode` takes whatever the tool
returns and stuffs it into a `ToolMessage` that goes back to the LLM. Strings
are what the LLM will see in its conversation history, so we serialize
explicitly to keep the representation stable.

---

## 3. The chat model

See [cyberpunk/agent/llm.py](cyberpunk/agent/llm.py).

```python
return ChatOllama(
    model=config.llm.model,
    base_url=config.llm.base_url,
    temperature=config.llm.temperature,
    num_predict=config.llm.max_tokens,
    client_kwargs={"timeout": config.llm.timeout},
)
```

`ChatOllama` (from `langchain-ollama`) is a concrete implementation of
LangChain's `BaseChatModel` interface. Anything that expects a `BaseChatModel`
will work with it — including `bind_tools()`, callbacks, streaming, etc.

### `bind_tools` — what it actually does

We **don't** bind tools here. Binding happens later in `build_graph`:

```python
model_with_tools = model.bind_tools(tools)
```

`bind_tools(tools)` returns a **new** model instance that, on every call,
automatically includes the tool schemas in the request payload and parses any
tool calls the model emits into structured `tool_calls` on the returned
`AIMessage`. The original `model` is untouched — which is why CyberPunk keeps
a tool-less copy around for the summarization pass (so the model literally
can't emit a tool call once it's been told to stop).

### Streaming tokens

`ChatOllama` streams by default. You don't see `.stream()` called anywhere in
CyberPunk's agent code — and that's because streaming is a **side channel**
here. It's captured through the callback system (next section).

---

## 4. LangGraph: the agent loop

See [cyberpunk/agent/graph.py](cyberpunk/agent/graph.py).

### State

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iteration: int
```

LangGraph threads a single state dict through the graph. Each node returns
a **delta** (a dict of fields to update), and LangGraph merges it into the
state.

The `Annotated[..., add_messages]` is a **reducer**. Without it, returning
`{"messages": [new_msg]}` would *replace* the whole list. With it, LangGraph
appends instead, and handles deduplication of messages by ID. This is the
standard pattern for conversation state.

`iteration` has no reducer, so returning `{"iteration": state["iteration"] + 1}`
overwrites the counter — which is what we want.

### Nodes

Three nodes:

```python
graph.add_node("agent", agent_node)
graph.add_node("tools", ToolNode(tools))
graph.add_node("summarize", summarize_node)
```

- **`agent_node`** — calls `model_with_tools.invoke(state["messages"])` and
  returns the response plus an incremented iteration. One LLM turn.
- **`tools`** — `ToolNode` is a LangGraph prebuilt that reads the last
  `AIMessage.tool_calls`, executes each tool, and returns a list of
  `ToolMessage`s. We didn't write this — LangGraph ships it because the
  "run whatever tools the model asked for" pattern is universal.
- **`summarize_node`** — the escape hatch. When iteration ≥ max, we inject
  a `HumanMessage` nudge ("you've hit the cap, summarize") and call the
  **tool-less** `model`. That guarantees the final message is plain text.

### Edges

```python
graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent", should_continue,
    {"tools": "tools", "summarize": "summarize", "end": END},
)
graph.add_edge("tools", "agent")
graph.add_edge("summarize", END)
```

The routing is entirely in `should_continue(state) -> str`. It returns a key
into the mapping dict — a common LangGraph pattern. Three outcomes:

1. iteration ≥ max → force summarize,
2. last message has `tool_calls` → run tools,
3. otherwise → we're done (model produced a natural final answer).

**Lesson:** conditional edges live *on* a node and route *out of* it. The
routing function sees the state *after* the node runs.

### Compile

```python
return graph.compile()
```

`compile()` turns the declarative `StateGraph` into a `CompiledStateGraph`
you can actually run. From here on, the graph is immutable — you can't add
nodes. Compile is cheap; CyberPunk compiles a fresh graph per run because
the bound tool list changes based on stealth mode.

---

## 5. Running the graph

See [cyberpunk/agent/agent.py](cyberpunk/agent/agent.py).

### Initial state

```python
state: AgentState = {
    "messages": [
        SystemMessage(content=system_prompt),
        HumanMessage(content=task_prompt),
    ],
    "iteration": 0,
}
```

Note these are LangChain message classes, not dicts. `BaseChatModel.invoke`
accepts either, but using the classes is typesafe and plays nicely with
`add_messages`.

### `stream(..., stream_mode="values")`

```python
for update in graph.stream(
    state,
    config={
        "callbacks": [callbacks],
        "recursion_limit": 2 * max_iterations + 4,
    },
    stream_mode="values",
):
    final_state = update
    current_iteration["value"] = update["iteration"]
    ...
```

Three things worth understanding:

1. **`stream_mode="values"`** yields the **entire state** after each node.
   The alternative `"updates"` yields just the delta per node. We want
   values because we read `update["iteration"]` to update the status panel.
2. **`recursion_limit`** is LangGraph's safety net against infinite loops.
   Each node visit counts as one "step". The agent↔tools cycle is two
   steps per iteration, so we budget `2 * max_iterations + 4` to leave room
   for START, summarize, and END without the runtime killing us before
   `should_continue` routes to summarize.
3. **`callbacks`** are passed in the runtime config, not the graph
   definition. Callbacks propagate to every child run (including the LLM
   and each tool call) automatically.

### Extracting the final answer

The terminal state's last message is always an `AIMessage` — either a
natural end (no tool calls) or the summarization output. We walk the message
list in reverse until we find one and return its `content`.

---

## 6. Callbacks: observability without wiring

See [cyberpunk/agent/callbacks.py](cyberpunk/agent/callbacks.py).

A `BaseCallbackHandler` gets notified of events during a run:

- `on_chat_model_start` — an LLM request is about to go out.
- `on_llm_new_token` — a streamed token has arrived.
- `on_llm_end` — the LLM finished; `LLMResult` contains the parsed message
  (with any tool calls) plus provider metadata (`llm_output`).

There are also `on_tool_start` / `on_tool_end` if you want them; CyberPunk
doesn't use those because the tool wrapper already handles that level.

### Why callbacks and not direct wiring?

Because the *graph* invokes the LLM, not our code. We never call
`model.invoke` ourselves at runtime — LangGraph does, from inside `agent_node`.
The callback system is the supported way to intercept what happens inside
those calls without reimplementing the node.

### Per-call isolation via `run_id`

```python
self._token_buffers: dict[UUID, list[str]] = {}
```

Every LangChain "run" has a UUID. We key the token buffer by `run_id` so if
two LLM calls ever happen concurrently the tokens don't get mixed. This is
the recommended pattern — do not use instance-level single buffers.

### Where `iteration` comes from

The callback doesn't know the graph's state. The agent runner passes in an
`iteration_provider` closure that reads from a mutable dict updated in the
`stream()` loop. That indirection lets callback-logged audit entries reflect
the iteration they were emitted in, even though callbacks fire inside the
LLM invocation, not from the graph node itself.

---

## 7. Putting it together

One agent run, end to end:

1. `AgentRunner.run(...)` builds the system + task prompts.
2. Tools are filtered (`available_tools(stealth)`) and wrapped
   (`wrap_tools_for_run`) with caching, stealth, audit, and status hooks.
3. `build_graph(model, tools, max_iterations)` binds tools to a model copy
   and compiles a `StateGraph` with three nodes.
4. `graph.stream(state, config={"callbacks": [...]})` drives the loop:
   - `agent_node` calls the LLM → tokens stream out through
     `on_llm_new_token` → `StatusDisplay` shows them live.
   - If the response has tool calls, `ToolNode` runs each wrapped tool.
     The wrapper consults the cache, executes via `run_command`, writes to
     audit, and returns a JSON string. `ToolNode` packages each result in a
     `ToolMessage`.
   - Back to `agent_node` for another LLM turn.
   - When the model finishes without calling tools (or iteration ≥ max),
     `should_continue` routes to END (or `summarize_node` then END).
5. `_extract_final_text(final_state)` returns the last `AIMessage.content`
   for the CLI to render.

---

## 8. Things to take away

- **Tools are just decorated functions.** Schema and description come from
  the signature and docstring. `tags` is your metadata hook.
- **`bind_tools` returns a new model.** It doesn't mutate. That's why
  CyberPunk keeps a bare model around for the tools-off summary pass.
- **State + reducers are the LangGraph idiom.** `Annotated[list, add_messages]`
  for conversations; plain ints for counters.
- **`ToolNode` is free.** You almost never need to hand-write the
  "run whatever tool the model asked for" loop.
- **Conditional edges route out of a node.** The routing function runs
  *after* the node, so it can inspect what the node just added to state.
- **Callbacks, not subclassing, for observability.** Token streams, timings,
  tool starts/ends — all via `BaseCallbackHandler`.
- **`recursion_limit` is your friend.** LangGraph won't let you loop forever,
  but you do have to budget enough steps for your chosen topology.

Once you internalize the node/edge/state triple and LangChain's message and
tool objects, reading (and writing) an agent becomes mechanical. The
CyberPunk agent, stripped of audit/status/stealth, is about 60 lines of
graph code — and that's the point: the libraries absorb most of what would
otherwise be orchestration plumbing.
