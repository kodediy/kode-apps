# The rules of the catalog

Every app in the catalog follows these rules. Each rule has an id, used by `tools/check_app.py`, in review issues and here. A rule's level says who judges it: **reject** fails the check, **warn** is reported in the pull request comment for the reviewer to look at, **review** is judged by the reviewer on a Kode Dot.

A passed check means every reject rule passed. It does not mean the app is good: the review rules are judged by a person, with the app running on a board.

Run the checks before you open the pull request, from a checkout of this repository, after building the app. The first command lists the published SDK releases that B1 compares the pin with; the second scans the app's history for secrets (C11) with the catalog's settings:

```bash
gh release list -R kodediy/kode-sdk --exclude-drafts --exclude-pre-releases --json tagName > releases.json
```

An app that uses a module SDK also lists that repository's releases, keyed by its git URL:

```bash
gh release list -R kodediy/kode-camera-sdk --exclude-drafts --exclude-pre-releases --json tagName | jq '{"git@github.com:kodediy/kode-camera-sdk.git": map(.tagName)}' > module_releases.json
```

```bash
gitleaks detect --source ../kode-app-<name> --config tools/gitleaks.toml --log-opts=HEAD --report-format json --report-path gitleaks.json --exit-code 0
```

```bash
python3 tools/check_app.py check --app ../kode-app-<name> --catalog . --build ../kode-app-<name>/build --sdk <a kode-sdk checkout at your pin> --kappdata-dir <KodeOS>/tools --releases releases.json --secrets-report gitleaks.json
```

Add `--module-releases module_releases.json` when the app uses a module SDK.

## A. Identity and package

| id | rule | level |
|---|---|---|
| A1 | The app lives in `kodediy/kode-app-<name>` and enters the catalog as the submodule `apps/<name>`, with the URL `../kode-app-<name>.git` in `.gitmodules`. Nothing else lives under `apps/`. | reject |
| A2 | `<name>` is the name in `project(<name>)`: 1 to 31 characters of `a-z`, `0-9` and `_`, the same in the repository name and the folder, used by no other app, and never `kodeos` or `c5_slave`. | reject |
| A3 | The code declares `KODE_APP_MANIFEST("Name", "cat1,cat2")` once: a display name of up to 31 characters and 1 to 4 categories of up to 15 characters, each one listed in `categories.txt`. | reject |
| A4 | `appdata/app.json` holds `"kode": "1"` and only the keys `color`, `description` and `icon`, within the limits KodeOS's `tools/kappdata.py` checks; `appdata/` holds an icon (`icon.png` or `icon.jpg`). The name and the categories come from the manifest, the version from the build. | reject |
| A5 | `LICENSE` is the text of the GNU GPL version 3, whole and unchanged (compared with this repository's `LICENSE`, whitespace aside). | reject |
| A6 | `CMakeLists.txt` has `set(PROJECT_VER "MAJOR.MINOR.PATCH")` before `project()`, and every new version of the app raises it. To go back to older code, publish it as a new, higher version. | reject |

## B. Build

| id | rule | level |
|---|---|---|
| B1 | Every `kodediy/*` dependency in `main/idf_component.yml` comes from `git@github.com:kodediy/kode-sdk.git` with `path: components/<name>` and no `override_path`, all at the same tag, and that tag is the newest published kode-sdk release or the one before it. A module SDK listed in `tools/module_sdks.txt` is the one exception: its dependencies come from its own repository, with the same `path` form and no `override_path`, all at one tag that is a published release of that repository. Write each dependency in the block form, its `git`, `path` and `version` on lines of their own below it, as the SDK examples do. | reject |
| B2 | `set(IDF_TARGET esp32p4)` comes before `project()`. | reject |
| B3 | The SDK comes from the pin in `main/idf_component.yml`, never as a submodule or through `EXTRA_COMPONENT_DIRS`, and `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME` is `"managed_components/kodediy__kbsp/partitions.csv"`. | reject |
| B4 | `sdkconfig.defaults` sets `CONFIG_KODEOS_BOOT_ROLE_APP=y`. | reject |
| B5 | Settings live in `sdkconfig.defaults` alone: no `sdkconfig.defaults.<target>` and no other file in `SDKCONFIG_DEFAULTS`; and it sets no key of the SDK's `sdkconfig.board`, except those in `tools/board_exceptions.txt`. The board's settings arrive with the SDK. The rules that read a setting (B3, B4, B7, C2, D8) read the resolved `sdkconfig` when there is one, since it wins over every defaults file. | reject |
| B6 | The app builds, and its `.bin` is at most 8 MiB (8,388,608 bytes). | reject |
| B7 | `CONFIG_KODEOS_RADIO=n` comes with `CONFIG_ESP_HOSTED_ENABLED=n` and `CONFIG_BT_ENABLED=n`; an app that calls `kode_mqtt_*` sets `CONFIG_KODEOS_CHANNEL=n`. | reject |
| B8 | The app keeps `ram_budget.txt`: a copy of the SDK's `tests/target/ram_budget.txt` without the lines of the Active Objects the app turns off, plus one line per large static of the app with its reason. Its `static_max` is not above the SDK's, or, when it is, the file says why in a `static_max_why <reason>` line and stays within 417,000 bytes, the static image kodeOS itself boots with on this board. The SDK's `tools/check_ram.sh` passes on the build. What the board needs is internal heap at run time: `test component=mem` (a floor of 64 KB, no refused allocation) after the app's heaviest path. | reject |
| B9 | The reviewer builds with the ESP-IDF version of the pinned SDK release. Build with the same one. | review |

## C. Behaviour at run time

| id | rule | level |
|---|---|---|
| C1 | Nothing is posted to an Active Object before `kode_init()` returns. | review |
| C2 | An Active Object never blocks: waiting work goes to a `kode_worker` or a task of the app. A blocking call in a file with state handlers is a warning; `CONFIG_KQP_AO_WATCH=n` is a reject. | warn |
| C3 | Ask a device's owner by event; never drive a device an SDK Active Object owns. Including an I2S, LCD, codec, Wi-Fi, NimBLE or SDMMC driver header is a warning. The expansion header is the app's through `kode_sys_exp_ctrl()`. | warn |
| C4 | Subscribe first, then ask the owner for its state. | review |
| C5 | The app's own signals start at `MAX_SIG` and are posted, never published. | warn |
| C6 | Events carry copies of their data, not pointers into the sender's tables. | review |
| C7 | Every `QACTIVE_START` comes after a `QActive_setAttr(..., TASK_NAME_ATTR, "<name>")` for the same Active Object. | reject |
| C8 | A worker's stack is at least 8192 bytes, and a job never touches flash or NVS. | warn |
| C9 | After the app's heaviest path, `test component=mem` passes on the board. | review |
| C10 | Nothing secret is stored with `kode_setting_*`: anyone can read it. | review |
| C11 | No credential anywhere in the app's history, scanned with the catalog's `tools/gitleaks.toml`. A secret that was rotated may be listed in `.gitleaksignore`, and every entry there needs the reviewer's explicit approval; a `.gitleaks.toml` of the app's own and an inline `gitleaks:allow` are refused. | reject |
| C12 | No `esp_ota_*` call and no direct flash write: `esp_partition_write`, `esp_partition_erase_range`, `esp_flash_write`/`esp_flash_erase_*`, `spi_flash_write`/`spi_flash_erase_*`. | reject |

## D. Interface

| id | rule | level |
|---|---|---|
| D1 | The interface is built with kui: its components, styles and tokens. | review |
| D2 | Nothing in the glass's R114 corners; full-width rows between y 53 and y 448 with 18 px side margins; no hairline on the edge (`kui_glass_inset()`, `kui_glass_rect_inside()`). | review |
| D4 | Only a tap acts: a press that travels more than 10 px acts on nothing. | review |
| D7 | A destructive action asks, then confirms; before going grey or dead the app says why. | review |
| D8 | Holding BOT returns to kodeOS from any app: never set `CONFIG_KODEOS_HOME_HOLD=n`, and give the hold no meaning of your own. | reject |
| D9 | `appdata/screenshots/` holds 1 to 4 PNG files of 410 x 502, taken with `kcli.py screenshot`. | reject |

### Pending style

These wait until the style is closed, and are not rules yet: D3, the button grammar; D5, one blue thing, the cursor; D6, a sheet with at most one answer button; D10, no status bar in an app; any limit on colours, fonts or layout.

## E. Code style

The style of the SDK's `components/khal`. Everything is in English.

| id | rule | level |
|---|---|---|
| E1 | Everything in English, the text on the glass included: no character outside ASCII in a source or build file (a reject); Spanish words in comments, strings or Markdown are a warning. | reject |
| E2 | Line 1 of every source is `/* SPDX-License-Identifier: GPL-3.0-or-later */`, followed by a `/**` block with `@file <file name>` and a one-line `@brief`. | reject |
| E3 | A header has a `NAME_H_` guard closed by `#endif /* NAME_H_ */`, and an `#ifdef __cplusplus` `extern "C" {` block. | reject |
| E4 | A header's blocks are separated by lines like `/* ---- Calls ---- */`. | warn |
| E5 | Every function in a header has `@brief`, an `@param` per argument and `@return` when it returns a value (a reject); every macro and field has a `/**< ... */` beside it (a warning). | reject |
| E6 | A brace on its own line after `if`, `else`, `for`, `while`, `do` and `switch`; `} else` split; `( cond )` spacing; every comparison in a compound condition in parentheses: `if ( (0U < n) && (NULL != p) )`. | reject |
| E7 | The constant or the value on the left of a comparison: `NULL == p`, `0U < n`. | reject |
| E8 | No ternary operator: an explicit `if` / `else`. | reject |
| E9 | Sized types (`uint8_t`, `size_t`...), never plain `int`, `unsigned`, `long` or `short`, except where an ESP-IDF API or `printf` needs one. | warn |
| E10 | No magic numbers: a named `#define` with its `/**< */`, and a `_Static_assert` where the code assumes a size or a limit. | review |
| E11 | `snake_case`; public names carry the module prefix; types end in `_t`; file statics start with `s_`; each file that logs defines `TAG` as `"module.sub"` and logs with `KLOG_*`, not `printf`. | warn |
| E12 | A `.c` file includes its own header first, then `<std...>`, ESP-IDF and the project, in groups. | warn |
| E13 | A `kode_status_t` that is ignored on purpose is cast to `(void)`; pointers that do not change are `const`. | warn |
| E14 | Short comments that say why, above each step that does not explain itself; no history, no bench measurements. | review |
| E15 | Four spaces, no tab. | reject |
| E16 | In Markdown, one line per paragraph and per bullet. | warn |

Fix E6 and E7 with `python3 tools/cstyle.py blocks FILE` then `python3 tools/cstyle.py yoda FILE`; list what is left with `python3 tools/cstyle.py lint FILE`. List E9 with `python3 tools/basic_types.py --findings DIR`.
