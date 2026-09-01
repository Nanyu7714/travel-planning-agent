# Media Storage

Only store images that the project owns or is allowed to redistribute.

Use this directory structure for local files:

```text
media/
  cities/<city-slug>/cover/
  attractions/<city-slug>/<attraction-id>/cover/
```

For each file, create a matching `media_assets` record with:

- `storage_type=local_file`
- `storage_path` relative to this directory
- `url=/media/<relative-path>`
- source, author, license, attribution URL, alt text and verification status

Remote and object-storage images do not need a local file, but their source and license metadata are still required.
