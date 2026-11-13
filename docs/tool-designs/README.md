# On-demand LLM tool assignments

This index tracks approved Codex handoffs and pending dev acceptance. They do not supersede the implemented architecture or represent deployed features. Pick **one document per PR**; preserve existing interfaces unless the assignment explicitly calls for a compatible extension. Avoid parallel changes to shared tool infrastructure. Each completed assignment should update the owner docs and be removed from this queue after operator acceptance.

1. [Enhance get_webpage_contents for complete, navigable article reading](01-webpage-reading.md)
2. [Enhance search_web with useful search metadata](02-brave-search.md)
3. [Archived Discord search](03-discord-history-search.md) (dev acceptance pending after rollout)
4. [Implement get_discord_message for a linked message](04-discord-message.md) (implemented in PR, dev acceptance pending)
5. [Implement get_steam_game_info for Steam store questions](05-steam-game-info.md)
6. [Implement get_reddit_discussion for public threads](06-reddit-discussion.md)
7. [Simplify IGDB game/platform lookup and cache authentication](07-igdb-interface.md)
8. [Implement get_discord_thread for actual reply chains](08-discord-thread.md) (dev acceptance pending after rollout)
9. [Implement get_movie_tv_info for entertainment lookups](09-movie-tv-info.md)
10. [Implement roll_dice and random_choice as bounded utilities](10-random-choice.md)
11. [Enhance weather_lookup with targeted forecast modes](11-weather-output.md)
12. [Implement get_github_repository for public project context](12-github-repository.md)
13. [Implement get_discord_member_info for permitted guild context](13-discord-member.md)
14. [Implement get_discord_channel_info for visible channel metadata](14-discord-channel.md)
15. [Implement create_discord_poll as an explicit on-demand action](15-discord-poll.md)
16. [Enhance get_webpage_contents with link-preview metadata](16-url-metadata.md)
17. [Standardize tool errors and budget-aware model behavior](17-tool-reliability.md)

Recommended first sequence: webpage reading → Brave search → Discord history → Discord message retrieval. Other assignments are independent except where they touch the same code. The reliability assignment can be implemented early or folded into targeted changes; avoid duplicating refactors.
