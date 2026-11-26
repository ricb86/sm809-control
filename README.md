# Software Mouse Gamer — SOLAKAKA SM809 Wired (RGB + Macros)

Software de controle para o mouse **SOLAKAKA SM809 Wired** em **Linux**, escrito a
partir da engenharia reversa do instalador oficial e de drivers open-source para o
mesmo controlador.

## Status

🟢 **Protocolo identificado e validado no hardware.** O mouse deste ambiente reporta:

- `VID:PID` = `04D9:A09F` (Holtek / E-Signal USB Gaming Mouse)
- `bcdDevice` = **`0301`** (firmware 3.01)
- Chave de ofuscação = **`FB1570`** (confirmada por leitura do firmware)
- Cor aplicada no teste: **`#0000ff`**, efeito `static`, brilho `0xFF`

## Stack escolhida

**Python 3 + `usbfs`/`hidraw` via `fcntl.ioctl` (somente stdlib).**

O protocolo são pacotes de 8 bytes; não há necessidade de compilação ou
dependências externas nesta fase. A arquitetura é em camadas:

```
src/sm809/protocol.py   # cipher, checksum, montagem de pacotes
src/sm809/usbfs.py      # backend para firmware 3.x (interface 2, sem hidraw)
src/sm809/device.py     # backend hidraw para firmware 2.x
src/sm809/config.py     # RGB, botões, macros, perfis
src/sm809ctl.py         # CLI
```

## Instalação (.deb)

```bash
# Gerar o pacote (requer dpkg-deb)
./packaging/build_deb.sh

# Instalar
sudo apt install ./dist/sm809-control_1.0.0_all.deb
```

Após instalar:

- `sm809-gui` — aplicativo com ícone (também aparece no menu “Utilitários”)
- `sm809ctl` — linha de comando
- regra udev instalada em `/lib/udev/rules.d/99-sm809.rules`

Os dados do usuário ficam em `~/.local/share/sm809/`.

A aba **Luz** do aplicativo replica a organização do driver original: os 12
efeitos em duas colunas (incluindo os modos de alternância do firmware de
fábrica), ajustes de brilho/frequência/comprimento, cor fixa ou ciclo de 8 cores
com paleta gravada no mouse e uma prévia do mouse. O botão **Restore Blue** volta
ao azul estático usado neste projeto.

## Uso

```bash
export PYTHONPATH=src

# Identificar o mouse e ler estado atual (somente leitura)
python3 src/sm809ctl.py detect

# Deixar o LED azul estático (faz backup antes)
python3 src/sm809ctl.py rgb 0000ff --effect static --yes

# Outros comandos
python3 src/sm809ctl.py effect breathing --p1 3

# Listar/remapear botoes do perfil 1 (funciona em 3.x e 2.x)
python3 src/sm809ctl.py buttons list --profile 1
python3 src/sm809ctl.py buttons set 11 key-a --profile 1

# Macro: gravar pagina 1 e listar eventos
python3 src/sm809ctl.py macro write --page 1 --file examples/macro-exemplo.json
python3 src/sm809ctl.py macro read --page 1

# Perfil completo: LED + botoes + macros
python3 src/sm809ctl.py profile save azul
python3 src/sm809ctl.py profile apply azul
python3 src/sm809ctl.py profile list
```

### Ações de botão aceitas

`left`, `right`, `middle`, `back`, `forward`, `dpi-up`, `dpi-down`, `dpi-cycle`,
`scroll-up`, `scroll-down`, `scroll-right`, `scroll-left`, `profile-up`,
`profile-down`, `profile-cycle`, `rate-125/250/500/1000`, `key-a` (ou `key-04`),
`macro-1` a `macro-9` (opcional `-0/1/2` para modo), `multiclick-left-3`,
`disabled`.

O formato dos eventos de macro é o `holtek8_macro_event`:

```json
{"key": 4, "press": true, "delay": 1}
{"key": 0, "command": 1, "wait": 50}
```

`command=1` é `WAIT`; `wait` conta em unidades de **2 ms** (50 = 100 ms).

Neste ambiente (Flatpak), execute no host com:

```bash
flatpak-spawn --host env PYTHONPATH="$PWD/src" python3 "$PWD/src/sm809ctl.py" detect
```

### Permissão USB

O nó `/dev/bus/usb/003/002` precisa ser gravável. Para não precisar de `pkexec`
a cada execução, instale a regra udev:

```bash
sudo cp udev/99-sm809.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Funcionalidades por firmware

| Recurso | Firmware 2.x (hidraw) | Firmware 3.01 (usbfs) |
|---|---|---|
| Cor RGB / efeitos | 12 modos | 12 modos (paleta `0x10` gravável) |
| Polling / DPI | sim | sim |
| Remapeamento de botões | sim (mapa 64 bytes, cmd `0x12`) | **sim** (4 perfis × 16 botões, bloco `0x03`) |
| Macros | sim (128 bytes/página, cmd `0x13`) | **sim** (9 páginas, bloco `0x03`) |
| Perfis locais | sim (JSON) | sim (LED + botões + macros) |

⚠ Firmware 3.x: **nunca** ler os grupos `0x09`, `0x10`, `0x11` ou `0x12` — isso
trava a interface ou exige reset USB. Tabelas são **somente escrita**; o estado
atual é mantido em `~/.local/share/sm809/buttons/` e
`~/.local/share/sm809/macros/` e parte do mapa de fábrica (`Data.ini`) quando
não há cache. Use `SM809_HOME` para sobrescrever esse diretório.

Os botões físicos DPI+/DPI- mudam a velocidade normalmente. O LED dedicado de
estágio DPI obedece à paleta da página 1 (`0x10 page 01`), mas neste firmware a
firmware não atualiza esse LED automaticamente quando o estágio muda; a opção
"Atualizar LED DPI ao trocar estagio" tenta reescrever a tabela, sem garantia
de refresco imediato.

A gravação foi validada no hardware: feature report `[0x12, perfil, 0x40]`
seguido de 2 blocos de 32 bytes e `[0x13, página, 0x80]` seguido de 4 blocos,
ambos com ACK e sem alterar o LED azul.

## Testes

```bash
cd src && python3 -m unittest discover -s tests -v
```

Os testes usam os vetores capturados (`27 28 f5 ff f0 0d 66 76` → chave `FB1570`)
e o vetor público do `PROTOCOLO_ARGUS.md`.

## Documentação

- [`docs/protocolo.md`](docs/protocolo.md) — especificação consolidada
- [`docs/engenharia-reversa.md`](docs/engenharia-reversa.md) — notas do processo
- [`docs/references/`](docs/references/) — fontes analisadas (DLL, drivers, capturas)

## Segurança

Toda escrita de luz é precedida de um backup automático em
`~/.local/share/sm809/backups/`. Para restaurar, use os valores do JSON com
`python3 src/sm809ctl.py rgb ... --effect ...`.
