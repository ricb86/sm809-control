# Protocolo — SM809 Wired (Holtek 04D9:A09F)

> Status: **reconstruído por análise estática e validado no hardware**.
> Mouse testado: `bcdDevice 0301`, chave `FB1570`, LED alterado para azul e relido com sucesso.

## 1. Identificação

| Campo | Valor |
|---|---|
| VID:PID | `04D9:A09F` (Holtek Semiconductor) |
| Nome comercial | SOLAKAKA SM809 Wired (com fio) |
| Sensor (Data.ini) | `3311` |
| Chave de ofuscação (Data.ini) | `Password=FB1570` |
| Firmware declarado no Data.ini | `Ver_H=2, Ver_L=1` |
| Firmware real medido no USB (`bcdDevice`) | `0301` |
| Chave confirmada no hardware | `FB1570` (reply de `0x80` → `80 03 01 00...`) |
| Canal de configuração | HID **Feature Report ID 0**, 8 bytes de payload (9 bytes no total) |

O instalador oficial (`SM809 Mouse Software.exe`) é um **Inno Setup** que contém
`SM809 mouse Software.exe`, `MSDriver.dll` (`hiddriver.dll`) e os dados em `app/Data/`.
O `MSDriver.dll` exporta `Set_VIDPID`, `Open_FeatureDevice`, `Open_ReportDevice`,
`SetFeature`, `GetFeature`, `WriteUSB`, `ReadUSB` — todos os comandos de configuração
passam por `SetFeature`/`GetFeature` com buffer de 9 bytes (report ID 0 + 8 bytes).

Outros projetos com o mesmo controlador confirmam o protocolo:
`docs/references/holtek-a09f-protocol-salahmak.md`, `PROTOCOLO_ARGUS.md`,
`driver-holtek-a09f-pr1915.c`, `holtek8a.c` (PRs 1561 e 1915 do libratbag).

## 2. Camada USB / HID

- Interface de configuração: **interface 2** (usage page `0xFF00`)
  - Feature report: 8 bytes (sem ID de report dentro do payload)
  - Report de saída (interrupt OUT): 32 bytes, usado para blocos de dados
  - Em alguns firmwares (3.x) a interface 2 não tem endpoint IN e o `usbhid` não cria
    `/dev/hidraw`; nesse caso é preciso `usbfs` (`USBDEVFS_CONTROL`).
  - Em firmwares 2.x (o caso provável do SM809) o hidraw funciona normalmente.
- Requisições (quando usando usbfs direto):
  - `SET_REPORT`: `0x21 / 0x09`, `wValue=0x0300`, `wIndex=2`
  - `GET_REPORT`: `0xA1 / 0x01`, `wValue=0x0300`, `wIndex=2`
- Com hidraw: `HIDIOCSFEATURE9` / `HIDIOCGFEATURE9` com 9 bytes
  (`byte 0 = 0` é o report ID; bytes 1..8 são o pacote).

## 3. Formato do pacote (8 bytes, "plaintext")

```
[cmd, d1, d2, d3, d4, d5, d6, chk]
chk = (0xFF - (cmd + d1 + d2 + d3 + d4 + d5 + d6)) & 0xFF
```

- **Escrita**: `cmd` com bit 7 = 0.
- **Leitura**: `cmd | 0x80`; a resposta vem no próximo `GET_FEATURE` como
  `[cmd|0x80, valores..., 00]` (sem checksum).
- Blocos maiores: um feature report `[cmd, page, length]` seguido de pacotes
  de 32 bytes pelo endpoint OUT.

### Ofuscação ("scramble")

Chave = 6 caracteres ASCII (`FB1570`). Aplicada a todos os pacotes:

```python
ADD = [0x25, 0xF6, 0xE4, 0x76, 0x47, 0x54, 0xE6, 0x76]

def scramble(p, k):
    q = [p[5], p[4]^k[0], p[7]^k[1], p[6]^k[2],
         p[1]^k[3], p[0]^k[4], p[3]^k[5], p[2]]
    v = int.from_bytes(bytes(q), 'big')
    v = ((v << 3) | (v >> 61)) & (2**64 - 1)   # rotação de 3 bits à esquerda
    q = list(v.to_bytes(8, 'big'))
    return bytes((q[i] + ADD[i]) & 0xFF for i in range(8))
```

A inversa (`unscramble`) subtrai `ADD`, rotaciona 3 bits à direita, desfaz o XOR
e a permutação. Pacotes com chave errada são silenciosamente ignorados pelo mouse
(falham no checksum).

### Como descobrir a chave

1. `Data.ini` do driver oficial traz `Password=FB1570` — tentar primeiro.
2. Se não funcionar: logo após plugar, um `GET_FEATURE` devolve
   `scramble(00*8, key)`, de onde se extrai a chave.
3. Depois disso o buffer fica com um pacote de status; nesse caso os caracteres
   3 e 5 da chave são descobertos por varredura (no máximo 256 tentativas).
   O projeto `a09fctl-reference.py` já implementa isso.

## 4. Comandos conhecidos

| Cmd | Leitura (`cmd|0x80`) | Escrita | Significado |
|---|---|---|---|
| `00` | `02 xx` | — | Versão de firmware (bcdDevice) |
| `01` | divisor | `01 div` | Polling: `01`=1000, `02`=500, `04`=250, `08`=125 Hz |
| `02` | — | `02 n` | Perfil ativo (hipótese, 1-based) |
| `03` | `02 0f d5 04` | `03 ...` | Desconhecido; driver oficial lê e reescreve igual |
| `0B` | — | `0b xx` | ? |
| `0C` | `R G B` | `0c R G B` | **Cor da roda** (usada pelos efeitos estático/padrão) |
| `0D` | `mode p1 p2` | `0d mode p1 p2` | **Efeito de luz** + 2 parâmetros |
| `10` | página 0/1 | `10 page 18` + 32B | Paleta do efeito Neon (8 × RGB) / cores dos estágios DPI |
| `11` | ⚠ ver nota | `11 05 08` + 32B | Tabela DPI (1 byte por estágio; bit 7 = desativado) |
| `12` | página 1 | `12 01 40` + 2×32B | **Mapa de botões** (64 bytes = 16 botões × 4 bytes) |
| `13` | `93` | `13 page 80` + 128B | **Dados de macro** (128 bytes por página) |

⚠ **Cuidado**: ler `0x89` (grupo `09`) trava a interface até desconectar o mouse.
Ler tabelas (`0x91`, `0x92` com página, `0x11`) pode fazer o mouse ignorar comandos
até um reset USB. Evitar leituras desnecessárias.

## 5. RGB / luz

12 modos (confirmado pelo `lan(CN).xml` do SM809 e pela tabela do protocolo C-13):

| Código | Modo | p1 p2 típico |
|---|---|---|
| `00` | Desligado | `00 00` |
| `01` | Constante (usa cor do `0C`) | `ff 00` |
| `02` | Respiração | `03 00` |
| `03` | Neon / ciclo de cores | `03 ff` |
| `04` | Onda | `03 ff` |
| `05` | Reação a tecla | `ff 00` |
| `06` | Rastro | `02 00` |
| `07` | Arraste | `02 00` |
| `08` | Deslizamento | `ff 00` |
| `09` | Yo-yo | `ff 10` |
| `0A` | Bolinhas | `ff 01` |
| `0B` | Estrela cadente | `ff 00` |

Velocidades: valores `00..04` (mais altos agem de forma errática). Para respiração:
`[10000, 4800, 3200, 2200, 1800]` ms; para ciclo: `[10000, 3670, 2000, 1400, 1070]` ms.
Brilho no modo constante: `p1` = 0..255.

## 6. Mapa de botões (`0x12`)

64 bytes = 16 entradas de 4 bytes: `[type, 0x00, code, 0x00]`.
O `Data.ini` do SM809 confirma exatamente esse formato (com um quinto campo de
"enabled" no arquivo do Windows):

```
1=01,00,F0,00,1     -> botão esquerdo
2=01,00,F1,00,1     -> botão direito
3=01,00,F2,00,1     -> botão do meio
4=01,00,F4,00,1     -> avançar
5=01,00,F3,00,1     -> voltar
6=07,00,01,00,1     -> DPI+
7=07,00,02,00,1     -> DPI-
8=0A,F0,32,03,1     -> ? (multi-clique / fire click)
...
```

| Type | Significado | Códigos |
|---|---|---|
| `00`/`0B` | desativado / não usado | — |
| `01` | função do mouse | `F0` esq., `F1` dir., `F2` meio, `F3` voltar, `F4` avançar |
| `03` | tecla de mídia (HID consumer) | `CD` play/pause, `B5` próx., `B6` ant., `E2` mute, `E9`/`EA` volume |
| `04` | roda | `01`, `02` |
| `07` | DPI | `01` DPI+, `02` DPI-, `03` ciclo |
| `09` | macro | índice da macro |
| `0A` | multi-clique | ver dados do Windows (`F0,32,03`) |

Slots do SM809: 1 esquerdo, 2 direito, 3 meio, 4 avançar, 5 voltar, 6 DPI+,
7 DPI-, 15/16 roda. Há 4 blocos de 16 no `Data.ini` (4 perfis no software).

## 7. Macros

- Paginação de 128 bytes por macro (`HOLTEK8_MACRO_DATA_SIZE = 128`).
- Cada evento ocupa 2 bytes:

```
byte 0: bit7 = release (1 = soltar), bits 0..6 = delay (mínimo 1)
byte 1: código HID da tecla (ou botão do mouse)
```

- Eventos especiais (quando `byte1` é comando):
  - `0x01` = WAIT, seguido de 2 bytes big-endian com delay em unidades de 2 ms
  - `0xFA` = movimento do mouse
  - `0xFE` = JUMP (para a próxima página)
- `repeat_count[2]` big-endian no início da página.
- Escrita: feature report `13 <page> 80` + bloco de 128 bytes no OUT.
- Leitura: `93 <page> 80`.

## 8. Perfis

- O software oficial guarda 4 perfis localmente (`profile.bin`, 117840 bytes),
  com 16 botões cada um, e aplica o ativo ao mouse.
- O mouse parece ter **1 perfil ativo** por vez; o comando `02 n` troca o perfil
  (hipótese a confirmar com captura).
- `profile.bin` e `Default.pbin` são idênticos no instalador; contêm nomes em
  UTF-16LE (`Profile 1`, `The default macro`, `The fire key`) e uma tabela de
  valores DPI em DWORDs little-endian no início.

## 9. Decisão de stack (recomendação)

**Python 3 + `hidraw` via `fcntl.ioctl` (stdlib), sem dependências externas.**

Motivos:
- O protocolo é simples, de 8 bytes — não precisa de Rust/C++ nesta fase.
- Permite testar hipóteses rapidamente com o mouse conectado.
- Os projetos de referência (`a09fctl.py`, `argus_proto.py`) já são Python.
- A arquitetura ficará em camadas (`protocolo` → `dispositivo` → `serviço` → CLI/GUI),
  permitindo trocar o backend depois (ex.: Rust + GTK) sem reescrever o protocolo.

## 10. Validação feita e pendências

Validado no mouse conectado (`E-Signal USB Gaming Mouse`, `04D9:A09F`, `bcdDevice 0301`):

1. ✅ `Password=FB1570` é a chave correta — o comando `80` responde `80 03 01`.
2. ✅ Leitura segura de `0C` (cor), `0D` (efeito), `01` (polling) e `0B`.
3. ✅ Escrita de `0C 00 00 FF` + `0D 01 FF 00` resulta em azul estático;
   leitura de volta confirma `#0000ff`, modo `01`, brilho `0xFF`.
4. ✅ Estado anterior salvo: cor `#f4f4f4`, efeito `03 00 ff`, polling 1000 Hz.

Validação adicional (botões e macros no firmware 3.01):

5. ✅ `12 <profile> 40` + 2 blocos de 32 bytes no EP `0x03` grava o mapa de
   16 botões. ACK: `12 00 02 00 40 00 00`; LED permanece `#0000ff`.
6. ✅ `13 <page> 80` + 4 blocos de 32 bytes grava a macro de 128 bytes.
   ACK: `13 01 03 00 80 00 00`; LED permanece `#0000ff`.

Ainda pendente (requer captura ou outro firmware):

1. Firmware 3.x suporta só 4 efeitos (`00` off, `01` estático, `02` respiração,
   `03` ciclo); os 12 modos do `lan(CN).xml` parecem ser do firmware 2.x.
2. O firmware 3.x **não devolve tabelas** (sem endpoint IN na interface 2), por
   isso botões/macros são somente escrita e o estado é mantido em cache local.
3. Troca entre os 4 perfis do software oficial (comando `02`?) não foi capturada.
4. Leitura da tabela DPI em 3.x é perigosa (pode travar até reset USB) e foi bloqueada.
