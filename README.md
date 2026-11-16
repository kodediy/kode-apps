# kode-apps

The catalog of the Kode Dot marketplace. Each app lives in its own repository and enters here as a submodule pinned to a reviewed commit; what is on `main` is what the marketplace publishes.

## Publishing an app

1. Start from [kode-app-template](https://github.com/kodediy/kode-app-template), in a repository `kodediy/kode-app-<name>`, and follow [RULES.md](RULES.md).
2. Open a pull request here that adds `apps/<name>` (`git submodule add ../kode-app-<name>.git apps/<name>`), or moves its commit to a new version.
3. Once a maintainer approves the run, the CI builds the app, runs the rules and leaves one comment with the result, the `.bin` and `appdata/`.
4. The reviewer installs the app on a Kode Dot, tries it and reads its repository. Anything to fix is an issue in `kode-app-<name>`: fix it there and move the pull request to the fixed commit.
5. With the approval and a green CI the pull request is merged, and the app is in the catalog.
6. The CI's run on `main` builds and checks the app again and puts that `.bin` on the marketplace, apps.kode.diy, under the slug `<name>` (`_` becomes `-`), submitted for review there. A maintainer can start that run by hand for apps already on `main` (the `app` workflow, Run workflow, the names separated by spaces): the way to publish an app whose push ran nothing or failed.

## The app repository

```
kode-app-<name>/
  CMakeLists.txt         set(IDF_TARGET esp32p4), set(PROJECT_VER "x.y.z"), project(<name>)
  sdkconfig.defaults
  main/idf_component.yml the kodediy/kode pin
  main/...               the sources
  appdata/app.json       "kode": "1", and only color, description, icon
  appdata/icon.png       the icon
  appdata/screenshots/   1 to 4 PNG files, 410 x 502
  ram_budget.txt         the app's internal-RAM budget
  LICENSE                GPL-3.0
  README.md
```

## This repository

- [RULES.md](RULES.md): every rule, its id and who judges it.
- `categories.txt`: the categories an app may declare.
- `tools/check_app.py`: the rule script; `tools/run_tests.sh` runs its tests.
- `tools/publish_app.py`: puts one app on the marketplace; the CI runs it on `main`.
- `tools/cstyle.py` and `tools/basic_types.py`: the style tools, to fix and to list.

Everything here is GPL-3.0-or-later, like the SDK.
