# Why not the Google Photos API

Since **2025-03-31**, the Google Photos Library API only sees media that the calling app
itself uploaded. The `photoslibrary.readonly`, `photoslibrary.sharing`, and full
`photoslibrary` scopes were removed and now return `403 PERMISSION_DENIED`; only
`*.appcreateddata` scopes remain.

Consequences:

- `mediaItems.list` / `mediaItems.search` / `albums.list` return **only app-created content** —
  not the user's existing library.
- There has **never** been an API to delete a user's library photos.
- The **Picker API** can't enumerate the library (the user must hand-pick items per
  short-lived session).

**Therefore:** the only complete source of the user's existing photos + metadata + album
structure is a **Google Takeout export**. This drives the whole architecture
(see [efficiency-architecture.md](efficiency-architecture.md)).

Sources:
- https://developers.google.com/photos/support/updates
- https://developers.google.com/photos/library/reference/rest/v1/mediaItems/list
