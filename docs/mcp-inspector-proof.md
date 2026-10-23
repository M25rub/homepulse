# Proof: HomePulse's MCP server, called through the official MCP Inspector

Captured with `@modelcontextprotocol/inspector` (CLI mode) against `python run.py`, Streamable HTTP.

**1. No token is refused**

    $ curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/mcp -d '{}'
    401

**2. Ask for a change. The answer comes back at once as PENDING (the backup-route lock is "cloud_down" in the sample home)**

    $ npx @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --transport http \
        --header "Authorization: Bearer homepulse-demo-token" \
        --method tools/call --tool-name set_device_state \
        --tool-arg device_id=back_lock --tool-arg capability=lock --tool-arg value=locked

    { "status": "PENDING",
      "command_id": "cmd_088409eed48a",
      "next_action": "Call get_command_status with command_id 'cmd_088409eed48a' to verify execution.",
      "retry_after_ms": 500,
      "target_device": "Back door lock" }

**3. Ask for the verified result**

    $ ... --method tools/call --tool-name get_command_status --tool-arg command_id=cmd_088409eed48a

    { "status": "VERIFIED",
      "how": "needed the backup (local) route",
      "summary": "Back door lock: lock -> locked: confirmed 1 of 1 checks.",
      "explanation": ["Back door lock: the usual internet route did not get through, so HomePulse used the backup (local) route and confirmed lock is locked."],
      "elapsed_ms": 465,
      "steps": [{ "device": "Back door lock", "desired": "locked", "reported": "locked", "verified": true,
                  "result": "recovered by local fallback", "attempts": 3, "routes_tried": ["cloud", "cloud", "local"] }] }

The device is simulated (see the README), but the contract is real: PENDING first, then one honest final answer.
