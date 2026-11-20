# Dev-стенд (IDEmu) — тестовое окружение для пакета

> **Язык:** [English](dev-stand.md) · Русский

**Dev-стенд** запускает родной софт головы NBT EVO в эмуляции — чтобы тестировать изменения evocode,
писать для него новый инструментарий или разрабатывать пользовательские программы на реальном QNX/HMI,
без машины. Используется [IDEmu](https://github.com/herrbimmer/IDEmu) (на QEMU; лицензия: PolyForm
Noncommercial — личное / исследовательское использование). Upstream охватывает CIC и iDrive 5–8;
здесь рассматривается NBT EVO / iDrive 5/6 на macOS, ниже есть путь для Linux/WSL. Стенд — удобство
разработчика, не часть evocode.

Сверено с upstream `main` [`d03ecd84f363`](https://github.com/herrbimmer/IDEmu/tree/d03ecd84f363)
2026-11-20: [Linux/WSL](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/LINUX.md) и
валидированный [профиль шима 18-03](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/NBT_PROFILES.md)
уже влиты. [PR #16](https://github.com/herrbimmer/IDEmu/pull/16) открыт и не влит: его head
[`d73b049`](https://github.com/FreZZZeR/IDEmu/commit/d73b049d8f69e146b08018e8204a516a9bb7b501) включает main `d03ecd8`; по проверке
GitHub 2026-11-20 — `mergeable=true`, `clean`, конфликтов нет. Реестр пока вне upstream `main`.
На этой ветке 2026-11-20 заново собраны и cold-boot до живого HMI проверены четыре точных набора
`007` (`007_051_002`, `007_001_016`, `007_030_001`, `007_039_008`) с проверкой companion hashes
и 29 адресами. Исторические наблюдения загрузки/SSH ниже относятся к 2026-11-11.

Чтобы *пользоваться* готовым стендом для репетиции свопа blobB и валидации `fw`, см.
[testing.md](testing.ru.md). Эта страница — про то, как стенд *поднять* и что на нём разрабатывать.

## Что на стенде можно разрабатывать, а что нет

| ✅ На стенде | ❌ Не на стенде |
|---|---|
| **Хореография** `fw` (remount / бэкап / rename-over / chmod) на живом QNX, через `fw --modern` | **Диагностическая плоскость** (HSFZ 6801): `write`, `fsc apply`/`read`, `root` — IDEmu её не выставляет |
| HMI-плагины, редактор кодировок / FDL, программы QNX-слоя (SSH / ФС / сервисы / права / slog) | **Транспорт** файла у `fw` — консольный мост дропает exec-stdin (§4) |
| UI-часть афтермаркет-плагинов, виртуальные CAN/GPS и cluster/HUD, карта на поверхности HMI от хоста | Радио/медиа/аудио, USB, BMW-навигация/маршруты, реальные сети машины, живой AA / CarPlay |

**Крипта и парсинг** evocode (`sign`/`verify`/`mint`/`recover-key`/`build-catalog`/`find-blobb`/
`patch-blobb`, SREC, каталоги) стенда **не требуют** — это офлайн и покрыто `pytest`. Стенд — для среза
«файловая система / HMI / QNX» на устройстве.

## Пререквизиты (macOS, Apple Silicon)

- Apple Silicon (arm64), macOS 14+.
- `brew install ninja pkg-config glib pixman`
- Python ≥3.10 чтобы *сконфигурировать* QEMU (сам IDEmu работает на системном `/usr/bin/python3`).
- clang (Xcode Command Line Tools) для рендерера `glhost`.

## 1. Собрать IDEmu (кастомный QEMU + рендерер)

Штатный `tools/qemu/build.sh` в IDEmu собирает x86_64 / iDrive7; для iDrive6 / ARM (NBT EVO) собираем цель
`omap5-uevm` по его `src/qemu/README.md`.

```bash
git clone --depth 1 https://github.com/herrbimmer/IDEmu && cd IDEmu
IDEMU_SRC="$PWD"
mkdir -p bin
bash src/glhost/build.sh                        # -> bin/glhost (рендерер OpenGL; работает headless)

W="$HOME/idemu-qemu"; mkdir -p "$W"; cd "$W"    # дерево сборки QEMU, вне репозитория
curl -fsSL -o qemu-11.1.2.tar.xz https://download.qemu.org/qemu-11.1.2.tar.xz
tar xf qemu-11.1.2.tar.xz; SRC="$W/qemu-11.1.2"
cp "$IDEMU_SRC/src/qemu/omap5-uevm.c" "$SRC/hw/arm/omap5-uevm.c"
( cd "$SRC" && patch -p1 < "$IDEMU_SRC/src/qemu/qemu-v11.1.2-idemu.patch" )   # правит Kconfig + meson.build
mkdir -p "$W/build" && cd "$W/build"
"$SRC/configure" --python="$(command -v python3.13)" --target-list=arm-softmmu \
  --disable-docs --disable-guest-agent --disable-tools --disable-gtk --disable-sdl \
  --disable-vnc --disable-curses --disable-rust --disable-user --disable-linux-user \
  --disable-bsd-user --without-default-features --enable-tcg
ninja qemu-system-arm
# macOS шлёт SIGKILL при перезаписи работающего файла — копировать в новое имя, затем mv:
cp qemu-system-arm "$IDEMU_SRC/bin/qemu-system-arm.new"
mv "$IDEMU_SRC/bin/qemu-system-arm.new" "$IDEMU_SRC/bin/qemu-system-arm"
"$IDEMU_SRC/bin/qemu-system-arm" -M help | grep omap5      # ждём: omap5-uevm
```

Для Linux/WSL следуйте [руководству upstream](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/LINUX.md):
Python ≥3.10, OpenGL/GLUT/libpng и зависимости QEMU, затем `bash tools/qemu/build-arm-linux.sh`
и `bash src/glhost/build.sh`. Upstream проверил Ubuntu 24.04 под WSL2 с Mesa llvmpipe; для headless
используйте `xvfb-run` и `IDEMU_NO_SNAPSHOT=1`, поскольку восстановление snapshot там не валидировано.

## 2. Прошивка — своя SWFL

IDEmu собирает образ диска из **SWFL** из **вашей собственной лицензионной полной PSdZData** (ничего не
поставляется). Для NBT EVO (iDrive6) нужны **три контейнера, все одной версии**:

| Роль | Файл | ~размер |
|---|---|---|
| OS | `swfl_0000271a.bin.<версия>` | ~880 МБ |
| HMI | `swfl_00002720.bin.<версия>` | ~710 МБ |
| бренд | `swfl_00002719.bin.<версия>` | ~480 МБ |

**Сверяйте профиль шима, а не только номер версии.** В upstream теперь два профиля фиксированных адресов:

| `shim_profile` окружения | HMI SWFL | Валидированный scope |
|---|---|---|
| не задан / `default` | `007_051_002` (24-03) | Прежняя функциональность IDEmu |
| `1803` | `006_017_006` (18-03) | Домашний экран, перенаправление поверхности карты, ротор и кнопки |

Builder сверяет хэши `HmiMain3D`, `libhmicom.so` и `libhmicoding.so` с
`idemu/data/known_hmi.json`; в `build.json` должно быть `hmi_validated: true`. Соседняя версия прошивки
не становится совместимой из-за похожего номера. Неизвестная сборка с default-профилем может остаться
невалидированной; явно неподходящие профили отклоняются.

Для 18-03 соберите отдельные библиотеки с `libc.so.3` из соответствующей прошивки:

```bash
SHIM_PROFILE=1803 bash src/shim/build.sh /path/to/18-03/boot/lib/libc.so.3
```

Остановите окружение и перед сборкой задайте `"shim_profile": "1803"` в его `env.json`.
Ассистент/API create/update не сохраняют это поле. Переменная сборки `SHIM_PROFILE` не выбирает
профиль окружения. Не смешивайте сгенерированные DSO из `lib` и `lib-1803`.
Touch, TPM, Lua/debug-хуки и восстановление snapshot для 18-03 **не валидированы**.

Наша `006_016_002` — другая прошивка: ни upstream 18-03, ни четыре `007` из реестра не проверяют
её HMI/ABI плагина. Для точного стенда по-прежнему нет полного matching SWFL и валидированного
профиля шима. Linux/WSL и новый boot 18-03 локально не повторяли.
В окружениях PR #16 старые manifests без companion hashes требуют полной пересборки из исходных
SWFL перед обновлением shim/записью кодировки; сначала сохраните изменения образов.

В наших тестах 2026-11-11 был живой HMI `007_051_002`; `007_001_016` зависал около 90 %, а его
OS/brand с HMI `007_051_002` давали сбой сервисов. Это датированные наблюдения, а не правило «версия
машины всегда без HMI». Загрузка только системного слоя проверяет QNX/SSH, но не `NBTCarHU`, который
так и не стартовал.

Lite-PSdZData (пустой `swe/swfl`) не подойдёт; нужна полная. SWFL держите вне репозитория — это ваши
лицензионные данные.

## 3. Create, build, run

Из репозитория IDEmu, на `/usr/bin/python3`:

```bash
python3 -m idemu gui                 # веб-UI (http://127.0.0.1:8765): ассистент «New environment»
python3 -m idemu list                # список окружений
python3 -m idemu build <id>          # собрать образ из выбранной SWFL (~20–30 с)
IDEMU_NO_SNAPSHOT=1 python3 -m idemu run <id>    # cold-boot; ждать состояния «running» (1–4 мин на TCG)
```

Ассистент (или `server.APP.create({...})`) принимает три пути SWFL, шасси и VIN для декода. Эмуляция
одноядерная (TCG) и медленная — дайте загрузке идти в фоне, не поллите. Стоп — Ctrl+C или
`pkill -INT -f "idemu run <id>"`; `idemu build <id>` пересобирает образ и сбрасывает его.

## 4. Подключение — и повадки моста

```bash
ssh -F environments/<id>/ssh/ssh_config idemu        # root-консоль гостя
```

Точка SSH — это **мост на стороне macOS** (ключ ed25519), а не собственный sshd гостя. Что это значит для
инструментов, которые вы под него пишете:

- **Нет `scp` / `sftp` / `rsync`** — мост блокирует их. Передача файлов есть во внутренних помощниках
  `idemu/sshshell.py` / `guestfs`; `python3 -m idemu push` / `pull` / `ssh` в этой ревизии не реализованы,
  хотя текст моста/help их предлагает. Для шелла используйте SSH-конфиг выше.
- Он **не прокидывает exec-stdin** — `ssh idemu 'cat > f'` пишет **0 байт** (проверено и системным
  клиентом, и paramiko). Трюки с upload, которые работают против настоящего sshd, здесь не сработают.
  (Поэтому `evocode fw` проверяет на стенде только *хореографию*; его upload сверяется по размеру и
  прерывается при несовпадении, так что ограничение моста не даст кривой установки.)
- В нашем госте 2026-11-11 не было `/tmp`, `tr` и `head`; проверяйте набор утилит конкретной прошивки.
- **Диагностический HSFZ (6801) не выставлен** — диагностическая плоскость со стенда недостижима.

## 5. Как разрабатывать evocode на стенде

- **Крипта / кодировка / FSC / каталоги** → `pytest`, офлайн; стенд не нужен.
- **Изменения `fw`** → гонять хореографию против моста с `fw --modern`; транспорт подтверждать на живой машине.
- **Новые HMI-плагины, редактор кодировок / FDL, программы QNX-слоя** → стенд с живым HMI (SWFL валидированной версии).
- **Работа с диагностической плоскостью** (`hsfz` / `uds` / `write` / `fsc apply` / `root`) → не на IDEmu;
  живой юнит или мок HSFZ.

## Заметки

- Лицензия IDEmu: PolyForm Noncommercial 1.0.0 (личное / исследовательское использование).
- Держите заведомо рабочий HMI/профиль и окружение версии машины, если они различаются.
- Виртуальные CAN/GPS и карта от хоста помогают тестировать UI, но не проверяют физические шины,
  BMW-навигацию, принятие FSC или реальный диагностический интерфейс.
