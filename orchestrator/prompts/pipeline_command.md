# Pipeline Command Template

This template is used to generate commands sent to Claude Code for each pipeline step.

## How it works

1. Python orchestrator determines which step to run
2. Python generates a command using the step's agent, inputs, and output file
3. Command is sent to Claude Code via stdin
4. Claude Code spawns the appropriate agent (via Agent tool)
5. Agent generates the output file
6. Python monitors for file creation and validates

## Command structure

```
# Pipeline Step: {step_name}

## Mode: {generate|review|revise}

You are {role_description}.

## Agent
Use the `{agent_name}` agent (run_in_background: true).

## Input Files
- {input1}
- {input2}
...

## Output
Save as: episodes/{episode_slug}/{output_file}

## {Instructions based on mode}

## Important
- Read all input files first
- Do NOT ask the user questions
- This is an autonomous pipeline execution
```

## Agent names

| Step | Agent name |
|------|-----------|
| design | kamishibai-generator |
| design review | kamishibai-reviewer |
| narration | narration-generator |
| narration review | narration-reviewer |
| image_prompt | image-prompt-generator |
| image_prompt review | image-prompt-reviewer |
| video_prompt | video-prompt-generator |
| video_prompt review | video-prompt-reviewer |
| bgm | bgm-prompt-generator |
| bgm review | bgm-prompt-reviewer |
| youtube | youtube-generator |
| youtube review | youtube-reviewer |
