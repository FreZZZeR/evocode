# Dev-стенд (IDEmu) — тестовое окружение для пакета

> **Язык:** [English](dev-stand.md) · Русский

**Dev-стенд** запускает родной софт головы NBT EVO в эмуляции — чтобы тестировать изменения evocode,
писать для него новый инструментарий или разрабатывать пользовательские программы на реальном QNX/HMI,
без машины. Используется [IDEmu](https://github.com/herrbimmer/IDEmu) (на QEMU, macOS; лицензия: PolyForm
Noncommercial — личное / исследовательское использование). Стенд — *удобство разработчика*, не часть
evocode; ниже — рабочая установка и, что не менее важно, её границы.

Чтобы *пользоваться* готовым стендом для репетиции свопа blobB и валидации `fw`, см.
[testing.md](testing.ru.md). Эта страница — про то, как стенд *поднять* и что на нём разрабатывать.

## Что на стенде можно разрабатывать, а что нет

| ✅ На стенде | ❌ Не на стенде |
|---|---|
| **Хореография** `fw` (remount / бэкап / rename-over / chmod) на живом QNX, через `fw --modern` | **Диагностическая плоскость** (HSFZ 6801): `write`, `fsc apply`/`read`, `root` — IDEmu её не выставляет |
| HMI-плагины, редактор кодировок / FDL, программы QNX-слоя (SSH / ФС / сервисы / права / slog) | **Транспорт** файла у `fw` — консольный мост дропает exec-stdin (§4) |
| UI-часть афтермаркет-плагинов (напр. UI Android Auto) | Медиа / аудио, USB, карты / навигация, сеть, живой AA / CarPlay |

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
`omap5-uevm` по его `src/qemu/README.md`. `<IDEmu>` ниже — путь клона.

```bash
git clone --depth 1 https://github.com/herrbimmer/IDEmu && cd IDEmu
mkdir -p bin
zsh src/glhost/build.sh                        # -> bin/glhost (рендерер OpenGL; работает headless)

W="$HOME/idemu-qemu"; mkdir -p "$W"; cd "$W"    # дерево сборки QEMU, вне репозитория
curl -fsSL -o qemu-11.1.2.tar.xz https://download.qemu.org/qemu-11.1.2.tar.xz
tar xf qemu-11.1.2.tar.xz; SRC="$W/qemu-11.1.2"
cp "$OLDPWD/src/qemu/omap5-uevm.c" "$SRC/hw/arm/omap5-uevm.c"
( cd "$SRC" && patch -p1 < "$OLDPWD/src/qemu/qemu-v11.1.2-idemu.patch" )   # правит Kconfig + meson.build
mkdir -p "$W/build" && cd "$W/build"
"$SRC/configure" --python="$(command -v python3.13)" --target-list=arm-softmmu \
  --disable-docs --disable-guest-agent --disable-tools --disable-gtk --disable-sdl \
  --disable-vnc --disable-curses --disable-rust --disable-user --disable-linux-user \
  --disable-bsd-user --without-default-features --enable-tcg
ninja qemu-system-arm
# macOS шлёт SIGKILL при перезаписи работающего файла — копировать в новое имя, затем mv:
cp qemu-system-arm "<IDEmu>/bin/qemu-system-arm.new"
mv "<IDEmu>/bin/qemu-system-arm.new" "<IDEmu>/bin/qemu-system-arm"
"<IDEmu>/bin/qemu-system-arm" -M help | grep omap5      # ждём: omap5-uevm
```

## 2. Прошивка — своя SWFL

IDEmu собирает образ диска из **SWFL** из **вашей собственной лицензионной полной PSdZData** (ничего не
поставляется). Для NBT EVO (iDrive6) нужны **три контейнера, все одной версии**:

| Роль | Файл | ~размер |
|---|---|---|
| OS | `swfl_0000271a.bin.<версия>` | ~880 МБ |
| HMI | `swfl_00002720.bin.<версия>` | ~710 МБ |
| бренд | `swfl_00002719.bin.<версия>` | ~480 МБ |

**Гвоздь версии — прочитайте.** Графический шим IDEmu прибит к конкретным сборкам HMI (валидированный хэш
`HmiMain3D` в его `idemu/data/known_hmi.json`). Поэтому:

- Для **живого HMI** (меню на экране — работа над плагинами / UI): все три роли — сборка, которую IDEmu
  *валидирует*, иначе HMI не финиширует (boot виснет ~90 %) и `NBTCarHU` (гейтится за HMI) не стартует —
  хотя **системный слой** (QNX / SSH / кодировка) поднят.
- Чтобы **совпасть с конкретной машиной** (напр. репетиция FSC): берите версию машины — тогда ждите
  только системный слой, без отрендеренного HMI. Это предел эмулятора, не вашего изменения.

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

- **Нет `scp` / `sftp` / `rsync`** — заблокированы; путь передачи у моста — `idemu push` / `idemu pull`.
- Он **не прокидывает exec-stdin** — `ssh idemu 'cat > f'` пишет **0 байт** (проверено и системным
  клиентом, и paramiko). Трюки с upload, которые работают против настоящего sshd, здесь не сработают.
  (Поэтому `evocode fw` проверяет на стенде только *хореографию*; его upload сверяется по размеру и
  прерывается при несовпадении, так что ограничение моста не даст кривой установки.)
- Гость минимален — нет `/tmp`, урезанный набор утилит (нет `tr` / `head`). Не закладывайтесь на них.
- **Диагностический HSFZ (6801) не выставлен** — диагностическая плоскость со стенда недостижима.

## 5. Как разрабатывать evocode на стенде

- **Крипта / кодировка / FSC / каталоги** → `pytest`, офлайн; стенд не нужен.
- **Изменения `fw`** → гонять хореографию против моста с `fw --modern`; транспорт подтверждать на живой машине.
- **Новые HMI-плагины, редактор кодировок / FDL, программы QNX-слоя** → стенд с живым HMI (SWFL валидированной версии).
- **Работа с диагностической плоскостью** (`hsfz` / `uds` / `write` / `fsc apply` / `root`) → не на IDEmu;
  живой юнит или мок HSFZ.

## Заметки

- Лицензия IDEmu: PolyForm Noncommercial 1.0.0 (личное / исследовательское использование).
- Удобно держать два стенда: валидированной версии — под HMI / плагины, и версии машины — под репетицию системного слоя.
- Стенд воспроизводит софт головы, но не её проводку: всё, что требует шин машины, медиа, сети или
  диагностического интерфейса, остаётся на машину.
