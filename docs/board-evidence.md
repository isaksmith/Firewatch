# Community board: what was run, and what was not

For a judge who does not read code. Every number below came from a command that was run on 2026-11-07. Where a number is an assumption, it says ASSUMED. All commands run from `backend/`.

## The test suite

- 499 backend tests pass (493 before the abuse tests were added). Command: `.venv/bin/python -m pytest -q`

## Can the board be abused?

Run with `.venv/bin/python -m pytest -q tests/test_board_abuse.py`. The tests go through the public web server, the same door a stranger would use. Each test was also shown to fail when its rule was deliberately broken.

| Attack | Result |
|---|---|
| 100 anonymous posts | 30 accepted, 70 refused by the rate limit. 0 events, 0 pages to firefighters. 3 neighbours were asked "did you see it?" once. |
| Confirming your own post | Refused (`own_post`). 0 counted, 0 events. |
| Confirming from 200 miles away | Not counted (`too_far`). 0 events, 0 signals. |
| Two strangers confirm each other | Stays at Investigate. 0 pages. |
| One member plus an anonymous tap | Stays at Investigate. The tap is not a full source. |

Note: the "two strangers" and "anonymous tap" rules were not mutation-checked, only the first three.

## Does the board make the alarm earlier? (A/B replay)

Command: `.venv/bin/python -m scripts.replay_board_ab`

The Cottonwood Creek replay was run twice: A as written, B with a member post at minute 27 and a neighbour confirm at minute 30. **Those two minutes are ASSUMED.** The replay clock and everything after them were measured.

| Scenario | First Escalate | First page | Dispatch |
|---|---|---|---|
| Packet, A | minute 0 | 3 | 9 |
| Packet, B | minute 0 | 3 | 9 |
| No co-op fault, A | 38 | 41 | 47 |
| No co-op fault, B | 30 | 33 | 39 |

- In the packet scenario the co-op line fault alarms at minute 0 on its own, so the board adds nothing. We say so plainly.
- Without the line fault, the board moves Escalate and the page 8 minutes earlier, if members post and confirm at those assumed minutes.

## Privacy and photos

- Public location rounding: 2 decimals, about 1 km. Test: `tests/test_routes_posts.py::test_location_rounding`, and `tests/test_routes_posts.py::test_reporters_own_position_is_stored_nowhere`.
- Photos: 2 MB cap, location data (EXIF) stripped, 10 uploads an hour per device (30 per IP). Tests: `tests/test_photos.py::test_upload_strips_exif_and_resizes`, `test_too_big_public_app`, `test_rate_limit_11th`, `test_photo_ip_limit_30_an_hour`.
- Offline posting: a post made without signal is sent later, and a repeat send makes one post, not two. Server side only: `test_repeat_client_key_is_one_post_one_event`, `test_queued_min_is_display_only`. Built and server-tested. The phone behaviour was not walked.
- Compass: a bearing and distance become an estimated point. Server side only: `test_compass_stores_computed_point_estimated` and the `test_compass_422` cases. Built and server-tested. Not tested outdoors.

## Where each plan check is covered

| Plan item | Test |
|---|---|
| 3. Abuse | `tests/test_board_abuse.py` (above), plus older `tests/test_posts.py::test_100_anonymous_posts_no_pages_one_round`, `test_confirm_from_200_miles_triggers_nothing`, `test_two_strangers_stay_investigate`, `test_anonymous_tap_is_never_full_source`, `test_own_post_and_duplicate_thanks` |
| 4. Ladder | `tests/test_posts.py::test_timer_once_and_only_high_danger`; dismiss by firefighters only: `tests/test_routes_posts.py::test_volunteer_cannot_dismiss_through_a_ladder_hold`; "not seeing it" keeps the post: `test_no_text_dismisses_the_event_not_the_post`. "Member plus member reaches Escalate" is covered by the replay B run, not by a named unit test. |
| 4. Acknowledge | `tests/test_ack.py`: `test_duty_ack_stops_the_ladder`, `test_volunteer_ack_does_not_stop_the_ladder`, `test_confirms_during_a_hold_send_no_texts_and_count_rises`, `test_satellite_hit_breaks_the_hold_with_one_text`, `test_post_ten_km_away_is_a_new_item`, `test_lapse_sends_one_text_to_duty_and_resumes_the_ladder`, `test_page_still_works_and_clears_the_hold`, `test_member_cannot_acknowledge`, `test_ack_text_matches_the_button` |
| 5. Text matches tap | `tests/test_posts.py::test_text_and_tap_match`, `test_reply_1_uses_newest_ask` |
| 6. Keywords | `tests/test_keywords.py` has small unit cases only. The 40-post spot check was not done. |

## Not tested yet

- Keyword spot check with 40 hand-written posts.
- Two-phone outdoor compass test.
- A real phone through Twilio.
- The demo video.
