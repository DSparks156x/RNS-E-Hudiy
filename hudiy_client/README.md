
# Hudiy data normalization

`hudiy_data.py` turns independent Hudiy callbacks into snapshots on the
`HUDIY_MEDIA`, `HUDIY_NAV`, `HUDIY_NAV_STATUS`, and `HUDIY_PHONE` ZMQ topics.
Queued snapshots are copied so later callbacks cannot change earlier updates.

## Navigation

`HUDIY_NAV_STATUS.api_active` reflects Hudiy's reported status. The normalized
`active` flag requires both an active Android Auto/CarPlay source and usable
route content. `has_route` describes that content: a meaningful instruction,
recognized distance, or arrival label. A maneuver type/icon alone does not
establish a route, and an absent protobuf state is treated as inactive.

On a fresh route, known maneuver details with no instruction can remain pending
and become available when their distance arrives. Repeated identical details
retain their matching distance; changed details discard the previous distance.
Explicit no-route labels, empty UNKNOWN details, inactive status, and provider
switches clear the route. While the provider keeps reporting ACTIVE, later bare
distance or type-only refreshes cannot resurrect a cleared route; meaningful
maneuver text must establish it again. A confirmed INACTIVE-to-ACTIVE transition
or an active provider switch starts a fresh pending route and allows icon details
followed by distance. Status alone remains insufficient. This conservative rule
may suppress an icon-and-distance route that resumes after a clear while its
provider continuously reports ACTIVE.

## Media and phone

Empty metadata for an established Android Auto/CarPlay track receives a one-second
grace period. Untitled artist/album-only projection updates receive a shorter
250 ms grace, including on the first track: the journals show these fields
arriving separately before the title. A titled update applies immediately and
cancels the pending update, preserving the previous track and cover during brief
transitions. Repeated incomplete snapshots replace the pending payload without
extending its original deadline. If no title arrives, the latest partial/empty
snapshot applies at the deadline. Source switches and service shutdown cancel
pending updates. Complete metadata arriving before a source status is preserved.

The observed idle snapshot with artist, title, and album all exactly `-` becomes
empty metadata only when the source is NONE and there is no artwork. A real `-`
title with other metadata or a known source is preserved. Initial empty snapshots
do not count as new tracks or emit unnecessary cover clears. Other sources and
tracks without prior metadata apply empty updates immediately. Metadata updates
also recompute paused/idle state; source NONE cannot remain marked playing.

Projection status reports visibility, as documented in
[Hudiy's API](https://github.com/wiboma/hudiy/blob/main/api/Api.proto);
becoming invisible does not itself end a route or playback session.

Phone connection and call state are separate. Disconnect clears callers and
cached levels, and only live call states assert `call_active`.

## Capturing provider behavior

`api_event_capture.py` records raw callback fields, explicitly present protobuf
fields, provider/context information, and normalized results in bounded rotating
JSON-lines logs at `~/logs/hudiy-api/hudiy-api-events.log`. Capture always starts
with the data API service, requires no configuration, and retains a current and
previous file bounded to 8 MiB each. **Save Logs** copies both complete captures
alongside the service journals into `~/logs/YYYY-MM-DD/<save number>/` (or the
configured Save Logs directory). DataView's file portal includes these saved
folders and the live captures. Every raw media
callback is recorded before normalization or deferral. Applied snapshots use
`media_metadata_applied`; deferred snapshots additionally record
`media_metadata_partial_applied` or `media_metadata_clear_applied` on expiry.
Timer applications do not duplicate the original raw callback.

The normalization rules are covered by callback-sequence tests, including the
two supplied startup journals. Those journals show partial media ordering but
only inactive/empty navigation, so raw captures during active navigation are
still needed to diagnose the reported route failure. The 250 ms and one-second
grace periods remain bounded heuristics rather than provider timing guarantees.
