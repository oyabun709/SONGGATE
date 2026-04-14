# RopQA Rules Reference

Rules are grouped by **layer**. Each rule lists its ID, severity, a plain-English description, which DSPs surface the issue, and the fix.

Severity levels:
- **critical** — Delivery will be rejected or content will not go live
- **warning** — Likely to cause playback issues, low quality scores, or DSP rejection
- **info** — Best-practice recommendation; won't block delivery

---

## DDEX Layer

Validates the structural integrity of DDEX ERN 4.3 packages.

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `DDEX_SCHEMA_VALID` | critical | Package must be well-formed XML conforming to ERN 4.3 schema | All | Fix XML syntax and re-validate against the ERN 4.3 XSD |
| `DDEX_ISRC_FORMAT` | critical | ISRC must match `CC-XXX-YY-NNNNN` (12 chars with hyphens) | All | Reformat ISRC; obtain from ISRC Agency if unknown |
| `DDEX_ISRC_UNIQUE` | warning | Each SoundRecording must have a unique ISRC within the package | All | Assign distinct ISRCs; do not reuse across tracks |
| `DDEX_UPC_FORMAT` | critical | UPC/EAN must be a 12 or 13-digit numeric string | All | Obtain a valid UPC from GS1 or your distributor |
| `DDEX_PUBLISHER_REQUIRED` | critical | Each SoundRecording must have at least one `Contributor/MusicPublisher` | Apple Music, Amazon | Add publishing information; use "Self-Released" if no publisher |
| `DDEX_DURATION_REQUIRED` | warning | `Duration` field must be present in ISO 8601 format (e.g. `PT3M45S`) | Spotify, Apple Music | Add duration to all SoundRecording elements |
| `DDEX_PARTY_REFERENCE_VALID` | critical | All `PartyReference` values must resolve to a `Party` in `PartyList` | All | Add missing parties or fix typos in references |
| `DDEX_RELEASE_DATE_FORMAT` | warning | `ReleaseDate` must be ISO 8601 `YYYY-MM-DD` | All | Reformat to `2024-03-01` style |
| `DDEX_GENRE_REQUIRED` | info | `Genre/GenreText` should be present on all SoundRecordings | Tidal, Deezer | Add genre; use the closest matching DDEX genre value |

---

## Metadata Layer

Validates content quality and completeness of metadata fields.

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `META_TITLE_EMPTY` | critical | Track or release title must not be empty | All | Provide a non-empty title |
| `META_ARTIST_EMPTY` | critical | Display artist name must not be empty | All | Provide the artist name |
| `META_LABEL_EMPTY` | warning | Label name must be present | Spotify, Apple Music | Add label name; use "Self-Released" if independent |
| `META_PLINE_REQUIRED` | warning | P-Line (phonographic copyright) must be present | Apple Music, Tidal | Add `PLine` with year and text (e.g. `2024 Label Name`) |
| `META_CLINE_REQUIRED` | info | C-Line (composition copyright) should be present | Apple Music | Add `CLine` with year and text |
| `META_EXPLICIT_DECLARED` | warning | Explicit content flag must be explicitly set (not omitted) | Spotify, Apple Music, TikTok | Set `IsExplicit` to `true` or `false` |
| `META_LANGUAGE_REQUIRED` | info | `LanguageOfPerformance` should be a valid ISO 639-1 code | Spotify, Deezer | Add two-letter language code (e.g. `en`, `es`, `fr`) |
| `META_TITLE_ALLCAPS` | info | Track titles should not be ALL CAPS | All | Use title case or sentence case |
| `META_TITLE_TRAILING_SPACE` | warning | Title must not have leading or trailing whitespace | All | Trim whitespace from title fields |
| `META_DUPLICATE_TITLE` | warning | Two or more tracks share the exact same title on one release | All | Add version suffixes (e.g. "Acoustic Version") to distinguish |

---

## Artwork Layer

Validates cover art technical specifications.

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `ART_REQUIRED` | critical | Front cover image must be included in the package | All | Include a `FrontCoverImage` resource |
| `ART_MIN_RESOLUTION` | warning | Cover art must be at least 3000×3000 pixels | Spotify, Apple Music, Amazon | Re-export at 3000×3000 px or larger |
| `ART_SQUARE` | critical | Cover art must be square (width equals height) | All | Crop or resize to square dimensions |
| `ART_COLOR_MODE` | warning | Artwork must be RGB color mode (not CMYK or Grayscale) | Spotify, Apple Music | Convert to RGB in Photoshop or equivalent |
| `ART_FORMAT` | critical | Artwork must be JPEG or PNG | All | Convert to `.jpg` or `.png` |
| `ART_MAX_SIZE_MB` | warning | Artwork file must be under 100 MB | All | Reduce file size by lowering quality or resolution |
| `ART_NO_TEXT_OVERLAY` | info | Cover art should not contain text overlay with DSP names or social handles | Spotify | Remove platform references from artwork |
| `ART_NO_EXPLICIT_IMAGERY` | critical | Artwork containing explicit sexual or violent imagery will be rejected | All | Replace with compliant artwork |

---

## Fraud Layer

Detects patterns associated with streaming fraud and artificial inflation.

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `FRAUD_MUSIC_SPAM` | critical | Track title matches known spam patterns (e.g. "Relaxing Study Music", "White Noise", "Rain Sounds") combined with duration under 60 seconds | Spotify, Apple Music | Review track; remove if content is not legitimate or extend duration |
| `FRAUD_SHORT_TRACK` | warning | Track duration is under 31 seconds | Spotify | Tracks under 31 seconds are ineligible for streaming royalties on most DSPs |
| `FRAUD_DUPLICATE_AUDIO` | critical | Audio fingerprint matches another track already in the catalog | All | Remove duplicate; submit original content only |
| `FRAUD_BULK_ISRC_SEQUENCE` | warning | 10+ tracks share ISRCs with sequential suffixes from the same registrant in a 24-hour window | Spotify, Apple Music | Review batch; artificial ISRC sequences are a known fraud signal |
| `FRAUD_HIGH_VELOCITY` | warning | Same org submitted more than 200 releases in the past 7 days | Spotify | Review pipeline; excessive velocity triggers DSP fraud review queues |
| `FRAUD_KNOWN_SPAM_ARTIST` | critical | Artist name matches an artist previously flagged for streaming fraud | All | Contact RopQA support if this is a false positive |

---

## Audio Layer

Validates audio file technical specifications (requires audio file ingestion).

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `AUDIO_FORMAT` | critical | Audio must be WAV (PCM), FLAC, or high-quality MP3 (320kbps+) | All | Re-export from the original session at a supported format |
| `AUDIO_SAMPLE_RATE` | warning | Sample rate must be 44.1 kHz or 48 kHz | Apple Music (Lossless) | Re-export at 44100 Hz or 48000 Hz |
| `AUDIO_BIT_DEPTH` | info | Bit depth should be 16-bit or 24-bit for lossless formats | Apple Music (Hi-Res) | Re-export at 24-bit for best quality |
| `AUDIO_CLIPPING` | warning | Audio has samples exceeding 0 dBFS (clipping detected) | All | Apply limiting in mastering to bring peaks below -0.1 dBFS |
| `AUDIO_SILENCE_START` | info | More than 5 seconds of silence at the beginning of the track | Spotify | Trim leading silence; Spotify auto-trims but may affect playback |
| `AUDIO_SILENCE_END` | info | More than 10 seconds of silence at the end of the track | All | Trim trailing silence |
| `AUDIO_MONO_CHECK` | info | Track is mono — many streaming DSPs expect stereo | All | Upmix to stereo if appropriate for the content |

---

## Enrichment Layer

Cross-references metadata against industry databases (MusicBrainz, Discogs, AllMusic).

| Rule ID | Severity | Description | DSPs Affected | Fix |
|---------|----------|-------------|---------------|-----|
| `ENRICH_ISRC_CONFLICT` | warning | ISRC is registered in the ISRC database to a different track or artist | All | Verify ownership; obtain a new ISRC if incorrect |
| `ENRICH_ISWC_CONFLICT` | info | ISWC resolves to a different composition title in CISAC | All | Verify and correct ISWC or remove if unknown |
| `ENRICH_ARTIST_NAME_VARIANT` | info | Artist name differs from the canonical form in MusicBrainz | Spotify (artist pages) | Use the canonical artist name to avoid split artist pages |
| `ENRICH_GENRE_MISMATCH` | info | Genre does not match the predominant genre in MusicBrainz for this artist | Spotify (editorial playlisting) | Review genre assignment for accuracy |

---

## Rule Customization

On **Professional** and **Enterprise** plans, rules can be:
- **Disabled** for your organization (e.g. `META_TITLE_ALLCAPS` if your style guide uses caps)
- **Escalated** from `info` to `warning` or `warning` to `critical`
- **Scoped** to specific DSPs only

Contact support or use the **Rules** page in the dashboard to configure.
