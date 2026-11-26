# Protocolo do mouse PCYes Argus (04d9:a09f) — notas de engenharia reversa

Canal de configuração: interface USB 2 (sem endpoint IN, por isso o kernel não cria hidraw).
- Feature report de 8 bytes (SET_REPORT 0x21/0x09, wValue 0x0300, wIndex 2; GET_REPORT 0xA1/0x01)
- Output report de 32 bytes (EP 0x03 OUT) — não usado pelo app na config.

Pacote (8 bytes): [cmd][d1..d6][checksum], checksum = 0xFF - cmd - sum(d1..d6) (mod 256).
Cifra (MouseDriver.exe 0x4160a0), chave = "Password" do Data.ini (FB1313), 6 bytes ASCII:
  1. permuta: out = [b5,b4,b7,b6,b1,b0,b3,b2]
  2. XOR chave nos bytes 1..6
  3. rotação de 3 bits à esquerda no valor de 64 bits (byte 0 = MSB)
  4. soma mod 256 de [25 f6 e4 76 47 54 e6 76]
Implementação: argus_proto.py (encrypt/decrypt/build/checksum).

Comandos vistos: 0x83 leitura de bloco (resposta: 83 + 6 bytes), 0x03 escrita, 0x01, 0x02, 0x0b, 0x0c.
Handshake capturado ao abrir o app (decifrado):
  SET 83 00 00 00 00 00 00 7c        (leitura)   -> resposta 83 00 0f f2 08 00 00
  SET 03 e7 00 72 40 08 5c ff        (escrita)
  SET 00 aa dd 3b 62 00 00 db        (enviado 1x sem cifra e 1x cifrado)
Estado atual do mouse: leitura 0x83 devolve tudo zero; sensor apagado; cliques funcionam.
