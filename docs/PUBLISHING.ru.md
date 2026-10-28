# Публикация форка: вручную и после проверки

Подготовка файлов не создаёт репозиторий, commit, push или Release. Адрес форка
согласован как `sososos662/StarRailAssistant-RU`; принадлежность GitHub fork
network и результат публикации нужно проверять отдельно. В примерах
`OWNER` / `REPOSITORY` — заполнители,
которые **нужно заменить** на реальные значения.

## Настоящий GitHub fork

1. На <https://github.com/Shasnow/StarRailAssistant> нажмите **Fork**.
2. Выберите свой аккаунт и имя. Если предлагается «Copy the main branch only»,
   снимите флажок, чтобы легче получить старый тег.
3. Склонируйте созданный fork в **новую пустую папку**, не поверх рабочей поставки.
4. Добавьте upstream и создайте ветку **от точного тега**, не от последнего main:

```text
git clone https://github.com/OWNER/REPOSITORY.git
cd REPOSITORY
git remote add upstream https://github.com/Shasnow/StarRailAssistant.git
git fetch upstream tag v2.25.0-beta.1
git rev-parse v2.25.0-beta.1
git switch -c ru-v2.25.0-beta.1 v2.25.0-beta.1
```

Ожидаемый SHA: `863509072bf2011b4d5a3e3d71072b6cd269637e`.
Копирование файлов в пустой GitHub-репозиторий не создаёт метку `forked from`.

## Перенос чистого комплекта

Скопируйте содержимое подготовленного `GitHub-ready` в клон, **не заменяя `.git`**.
Обязательно уберите из активного `.github/workflows/` шесть прежних workflow:
они перенесены в `.github/upstream-workflows-disabled/*.disabled`. Простое
копирование новых файлов не удалит старые workflow из клона!
Сверьте удаления с `FORK_CHANGES.json` и `git diff --name-status`; не удаляйте
неизвестные локальные файлы без проверки. Файл `SOURCE_MANIFEST.json` относится
к экспортированному комплекту и не содержит себя.

Для повторного экспорта из рабочих исходников:

```text
python scripts/export_source.py --output ../GitHub-ready-new --upstream-zip ../v2.25.0-beta.1-source.zip --zip ../StarRailAssistant-RU-Source-new.zip
```

Экспорт использует разрешённые каталоги, не `.gitignore` как единственную защиту.
Не включаются AppData, реальные журналы, сохранения, SDK, node_modules, bin/obj,
старые ZIP, Nuitka output и кэши. `vendor/` содержит только официальный закреплённый
DirectML wheel (~25 МБ); модели поставляются в runtime, не в Git.
В `extensions/cw_plus/strategies` экспорт разрешает два штатных JSON, исходный
JSONC и отдельно разрешённый владельцем `himeko_global_europe_20261026.json`
(«Химэко Нова — Европа»). Его код разрешён к публикации вместе с этим вариантом;
личные настройки аккаунта к нему не прилагаются. Остальные локальные копии не
попадают в исходники или public runtime. Для добавления другого варианта нужен
отдельный аудит и явное изменение списка экспорта.
Скрипт не может доказать отсутствие персональных данных внутри произвольной картинки:
просмотрите изменённые fixtures и результаты отдельного privacy-аудита.

Корневой и вложенный WebUI `.gitattributes` сохраняют исходные байты (`* -text`).
Не включайте автоматическую замену переводов строк: Git blobs должны совпадать
с `SOURCE_MANIFEST.json` и Source ZIP. Два сгенерированных файла WebUI
`auto-imports.d.ts` и `components.d.ts` входят в проверенный экспорт, хотя
игнорируются при обычной разработке. При первом переносе добавьте **только их**
явно, затем сверяйте полный состав индекса и содержимое каждого blob с экспортом.

## Чек-лист перед первым push

- [ ] На GitHub действительно указан `forked from Shasnow/StarRailAssistant`.
- [ ] Ветка создана от точного коммита базы, не от неизвестного HEAD.
- [ ] README/FORK/UPSTREAM/CHANGELOG отражают не только перевод, но изменения логики.
- [ ] LICENSE и оригинальные авторские уведомления сохранены.
- [ ] Нет UID/ников/домашних путей, токенов, webhook, личных настроек и сохранений.
- [ ] В активных workflow только `ci.yml` и `build-fork.yml`; публикационных секретов нет.
- [ ] Offline-тесты и блокирующий lint зелёные. Первый CI после push просмотрен отдельно.
- [ ] WebUI/API/MCP не открыт наружу с пустым AccessToken.
- [ ] Унаследованные ссылки на upstream не выданы за канал обновления форка.

Только после просмотра diff и согласия владельца:

```text
git status --short
git diff --stat
git add -A
git add --force -- SRAFrontend/srafrontend-webui/auto-imports.d.ts SRAFrontend/srafrontend-webui/components.d.ts
git add --renormalize -A
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --cached --check
git diff --cached --stat
git commit -m "feat(ru): 基于 v2.25.0-beta.1 的俄语分支和修复"
git push -u origin ru-v2.25.0-beta.1
```

При сохранении исходных CRLF `diff --check` может повторно показать пробелы
upstream, пустые строки и содержимое сгенерированных многострочных ресурсов.
Каждое замечание нужно просмотреть отдельно; это не повод массово переписывать
принятые исходники, строки локализации или разрешённый JSON стратегии.
Конфликтные маркеры и непроверенные изменения блокируют публикацию.

Чтобы ветка форка открывалась по умолчанию, выберите её в GitHub Settings → Branches.

## Release

Тег форка: `v2.25.0-beta.1-ru.20261028.1`, не чужой `v2.25.0-beta.1`.
Создайте сначала **Draft / Pre-release**, направленный на проверенный commit.
Текст: [RELEASE_NOTES.ru.md](RELEASE_NOTES.ru.md). Приложите runtime ZIP,
соответствующий Source ZIP и SHA256 обоих. Не прикладывайте приватный evidence,
оригинальные журналы и весь AppData. SHA256 подтверждает целостность файла,
но сам по себе не заменяет доверенную подпись издателя.

В `BUILD_INFO.json` нового build-сценария сохранены исходные SHA256 и версии;
проверяйте соответствие конкретного runtime и Source. Для ранее собранного
ядра с обновлёнными внешними модулями это должно быть честно отмечено, а не
названо полной новой компиляцией.
Не публикуйте fork как официальный PyPI-пакет `starrailassistant`, не используйте
R2/MirrorChyan upstream и не объявляйте новые полные игровые прогоны без проверки.
