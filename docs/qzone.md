# QQ Space module

`qzone.py` publishes short posts through NapCat's native `send_qzone_msg` action. The action was added in [NapCatQQ PR #1965](https://github.com/NapNeko/NapCatQQ/pull/1965). Mai Secretary calls the existing MaiBot NapCat adapter's public `adapter.napcat.action.call` API; it does not require a second QQ login or a QQ Space bridge.

1. Use a NapCat version that actually includes `send_qzone_msg`, and make sure its MaiBot adapter is connected.
2. Enable `[qzone].enabled` in the plugin configuration. Automatic posting remains off until `automatic_enabled` is set.
3. To use chat highlights, explicitly list `qq:private:QQ号` or `qq:group:群号` targets in `allowed_streams`. An empty list denies access to all chat histories. Review each allowed stream's privacy before adding it.
4. Administrators can ask MaiBot to call `secretary_qzone_post(action="publish", source="life"|"daily", include_image=true|false)`. `action="status"` checks recent results. The tool queues work; the final success or failure is reported back to the requesting chat.

For a manual post with no specified source, omit `source` or use `auto` to draw from the configured source probabilities. Omit `include_image` to use the photo probability; an explicit true or false overrides the draw.

`automatic_time` is in the plugin timezone and defaults to `20:30`. `post_probability` controls the daily draw (default 70%); `life_probability` controls the source draw (default 90% life, otherwise allowed chat highlights). An empty allowlist falls back to life. The legacy `automatic_source` setting is retained but no longer selects the automatic source. Life posts summarize recorded activities from the current day and reflect the current shared mood when enabled; periods before the history feature was installed or while MaiBot was offline may be absent. Scheduled posting is claimed once per day before any network call, including a skipped draw. Missed posts outside the configured grace period are skipped. An uncertain NapCat result is **not** automatically retried. `visibility` defaults to friends only, and `max_posts_per_day` defaults to one.

With `include_image` enabled, `image_probability` controls whether a post includes a photo (default 30%). An explicit manual request can override the draw. The module uses the configured Qwen life-photo API, the same global image cooldown and daily cap, and the ordinary first-person scene mode. Every image API request may incur a charge even if the later QQ Space publish fails.

A loaded Mai Secretary plugin by itself does not prove the installed NapCat version supports `send_qzone_msg` or that a post reached QQ Space. Verify the returned `tid` and check QQ Space itself. No QQ account token or cookie is stored in this module.
