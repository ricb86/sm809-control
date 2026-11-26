# Engenharia Reversa — Mouse Solakaka

Template para documentar o processo de engenharia reversa. Preencher com os dados reais.

## 1. Dispositivo

- **Nome comercial:**
- **Vendor ID (VID):**
- **Product ID (PID):**
- **Modelo / firmware:**
- **Conexão:** USB / sem fio (dongle) / Bluetooth
- `lsusb` relevante:
- `lsusb -v` (interfaces e endpoints):

## 2. Ferramentas usadas

- `usbmon` + Wireshark
- `hidraw` / `/dev/hidraw*`
- `evdev` / `libevdev`
- Outros:

## 3. Capturas

- [ ] Tráfego USB capturado ao trocar cor
- [ ] Tráfego USB capturado ao trocar efeito
- [ ] Tráfego USB capturado ao gravar/atribuir macro
- [ ] Tráfego USB capturado ao remapear botão
- [ ] Tráfego USB capturado ao salvar perfil

## 4. Investigação

### RGB

- Endpoint / report ID usado:
- Formato do pacote (bytes, offsets, significado):
- Cores: ordem dos canais (RGB/BGR), faixa (0–255),Gamma?
- Efeitos e seus códigos:
- Velocidade / brilho: como são codificados?
- Pacote de confirmação/resposta do dispositivo?

### Botões / remapeamento

- Como o dispositivo identifica cada botão (código HID, índice interno)?
- Report de configuração (offsets, máscaras):
- Mapa de funções suportadas (tecla, clique, mídia, macro, etc.):

### Macros

- Formato de armazenamento no dispositivo (slots, tamanho máximo):
- Codificação de eventos (tecla, delay, clique, modificadores):
- Como gravar via software (modo de aprendizado?):

### Perfis

- Quantos perfis o dispositivo suporta?
- Como selecionar perfil ativo?
- Configuração fica no dispositivo ou no computador?

## 5. Hipóteses e dúvidas

<!-- Anotar incertezas aqui -->

## 6. Conclusões

<!-- Resumo do que foi confirmado -->
