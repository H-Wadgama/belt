I need a very small temporary debugging change. Do not modify any workflow behavior.

In the Qwen agent/tool-execution loop, I currently see terminal output like:

```text
[calling get_binary_distillation_problem({})]
```

but I cannot see the literal result returned by the Python tool before that result is passed back to Qwen.

Please locate the exact code that:

1. receives Qwen's tool call,
2. invokes the Python tool,
3. receives the tool's return value,
4. passes/serializes that result back into Qwen.

Immediately after step 3 and before step 4, add temporary debug output that prints the COMPLETE raw tool result to the terminal.

Use `pprint` or JSON pretty-printing if appropriate so nested dictionaries are readable.

I want terminal output conceptually like:

```text
[calling get_binary_distillation_problem({})]

========== RAW TOOL RESULT ==========
{complete literal Python result here}
=====================================

Assistant: ...
```

Do not change:
- workflow state,
- tool schemas,
- prompts,
- calculation behavior,
- case-selection logic,
- Qwen behavior,
- return values.

This is diagnostic logging only.

After making the change, tell me the exact file and lines changed.