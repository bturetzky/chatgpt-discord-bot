# Archived Discord search dev acceptance

**Status:** Implemented in the review branch. Dev Discord acceptance is pending after rollout. See [SQLite server archive](../architecture.md#sqlite-server-archive) for behavior.

Use the dev bot and confirm the test messages are archived. Seed an older visible discussion with a distinctive phrase such as “space age launch”, a newer message containing the same words farther apart, and a separate marker in a channel the bot can read but the test requester cannot.

1. Ask “Which game did we discuss in the older space age launch conversation?” Expect the relevant older conversation and a link to its source.
2. Ask “Who said ‘space age launch’ exactly? Read the surrounding messages and tell me what they meant.” Expect attribution to the matching author and context from the same channel.
3. From the restricted account, ask for the private marker. Expect no private excerpt, author, channel or link.
