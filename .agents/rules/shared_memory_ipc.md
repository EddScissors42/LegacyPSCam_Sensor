# Regra Especializada — Memória Compartilhada e IPC com Just Dance PC

Esta regra aplica-se a `kinect_shared_memory.py` e a qualquer código que interaja com o arquivo de memória compartilhada consumido pelo `Kinect10.dll`.

---

## 1. Contrato da Memória Compartilhada do Windows

- **Identificador de Tag:** `Local\LegacyWebcamKinectPose`
- **Tamanho Total:** Exatamente **344 bytes**.
  - Qualquer alteração no tamanho do buffer causa violação de acesso (*Access Violation*) ou leitura de lixo de memória na DLL de 32 bits do jogo (`push 158h` / 344 bytes).
- **Alocação:** Mapeada via arquivo de paginação anônimo do Windows (`mmap.mmap(-1, 344, tagname=...)`).

---

## 2. Estrutura Binária e Layout de Memória

### Cabeçalho (24 bytes) — Formato `<IIIIQ` (Little-Endian)
| Campo | Tipo C | Tamanho | Descrição |
|---|---|---|---|
| `magic` | `uint32_t` | 4 bytes | Constante fixa `0x3150444A` (`'JDP1'`) |
| `version` | `uint32_t` | 4 bytes | Versão da estrutura: `1` |
| `seq` | `uint32_t` | 4 bytes | Sequência seqlock (veja seção 3) |
| `tracked` | `uint32_t` | 4 bytes | `1` se o esqueleto estiver ativo, `0` se não houver corpo |
| `timestamp_ms` | `uint64_t` | 8 bytes | Timestamp em milissegundos (`int(time.time() * 1000)`) |

### Dados das Articulações (320 bytes) — 20 Joints
- Cada articulação tem formato `<ffff` (16 bytes):
  - `x` (`float`): Posição lateral em metros (-1.0 a +1.0)
  - `y` (`float`): Posição vertical em metros (-1.0 a +1.0)
  - `z` (`float`): Posição de profundidade em metros (~2.0m)
  - `conf` (`float`): Confiança do rastreamento (1.0 = rastreado, 0.0 = não confiável)
- Total: 20 * 16 = 320 bytes.
- Total Geral: 24 + 320 = 344 bytes.

---

## 3. Protocolo Seqlock Lockless (Sem Travamentos)

Para evitar que o Just Dance PC leia um esqueleto pela metade enquanto o Python está gravando (o que causaria "teletransporte" de membros e perda de pontos), o protocolo seqlock deve ser estritamente mantido:

1. **Início da Gravação:**
   - O Python incrementa o número de sequência para um valor **ÍMPAR**:
     `self.seq = (self.seq + 2) | 1`
   - Grava o cabeçalho no offset 0 e chama `flush()`.
2. **Gravação dos 20 Joints:**
   - Escreve os 320 bytes de dados dos joints compactados via `struct.pack(FULL_JOINTS_FMT, *flat_joints)` de uma só vez (escrita única em lote, nunca 20 writes separados).
3. **Fim da Gravação:**
   - Incrementa a sequência para o valor **PAR** seguinte:
     `self.seq += 1`
   - Atualiza o campo `seq` no offset 8 e faz `flush()`.

A DLL do Kinect no Just Dance lê a sequência antes e depois dos dados. Se a sequência for ímpar ou mudar durante a leitura, a DLL sabe que houve sobreposição e repete a leitura, garantindo sincronia perfeita sem precisar de mutexes pesados de kernel.
