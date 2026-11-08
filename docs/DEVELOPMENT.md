# 💻 Guia do Desenvolvedor — Legacy PSCam Sensor

Este documento é o guia técnico para desenvolvedores que desejam manter, refatorar ou adicionar novos recursos ao **Legacy PSCam Sensor**. Ele define as convenções de código, diretrizes de segurança arquitetural, procedimentos de teste e boas práticas de engenharia.

---

## 📐 Padrões de Código e Convenções

O projeto segue estritamente as convenções padrão do ecossistema Python (PEP 8) com adaptações específicas para visão computacional de alta performance:

- **Nomenclatura:**
  - Classes: `PascalCase` (`CameraManager`, `AdaptiveSmoother`, `PoseTracker`).
  - Funções e Métodos: `snake_case` (`run_tracking_session`, `write_pose`, `_setup_styles`).
  - Constantes Globais: `UPPER_SNAKE_CASE` (`SHARED_NAME`, `JOINT_COUNT`, `THEME`).
  - Variáveis Privadas ou Internas: prefixo com sublinhado (`_capture_loop`, `_is_running`).
- **Manipulação de Caminhos:** Utilize exclusivamente `pathlib.Path` em vez de manipulação manual de strings com `os.path.join`.
- **Tipagem e Documentação:** Todas as novas classes e métodos públicos devem conter docstrings concisas e tipagem de argumentos e retorno quando aplicável.
- **Isolamento de SO:** Qualquer chamada a subprocessos ou comandos de sistema deve tratar `os.name == 'nt'` de forma segura, suprimindo janelas de prompt indesejadas via `subprocess.CREATE_NO_WINDOW`.

---

## 🏷️ Padrão Oficial de Versionamento e Título da Aplicação

O projeto adota uma convenção estrita de versionamento semântico pragmático centralizada em `version.py`:

```python
__version__ = "0.1.3"
STAGE = "Alpha"
VERSION_STRING = f"v{__version__} ({STAGE})"
WINDOW_TITLE = f"Legacy PSCam Sensor {VERSION_STRING}"
```

### Regras Obrigatórias de Incremento de Versão:
1. **Mudanças Pequenas (Bugfixes, ajustes de UI, novos assets/ícones):** Altere estritamente o **terceiro dígito** (`0.1.1` ➔ `0.1.2`).
2. **Grandes Mudanças / Refatorações Significativas:** Altere o **segundo dígito** (`0.1.2` ➔ `0.2.0`).
3. **Sempre atualizar:** Sempre que fizer uma modificação, incremente a versão em `version.py`.
4. **Título da Janela e Rodapé:** O título da janela principal (Qt e Tkinter) deve obrigatoriamente exibir o número da versão acompanhado de `(Alpha)` (ex.: `"Legacy PSCam Sensor v0.1.2 (Alpha)"`).

---

## 🛡️ Regras Inegociáveis de Segurança e Estabilidade

Qualquer desenvolvedor ou agente deve respeitar quatro regras de ouro para não quebrar a pontuação do jogo nem causar travamentos:

### 1. Preservação do Frame Bruto na Inferência
```python
# CORRETO: MediaPipe sempre recebe o frame como a câmera capturou
results = self.landmarker.detect_for_video(mp_image, timestamp_ms)

# ERRADO: Nunca inverta o frame antes da IA!
# frame_flip = cv2.flip(frame, 1)
# results = self.landmarker.detect_for_video(frame_flip, timestamp_ms)
# (Isso inverte braço esquerdo e direito, zerando a pontuação no jogo!)
```

### 2. Timestamps Estritamente Crescentes
O MediaPipe Tasks API em modo `RunningMode.VIDEO` lança `ValueError` fatal se receber dois frames com o mesmo timestamp em milissegundos. Sempre garanta:
```python
timestamp_ms = max(now_ms, self.frame_index)
if timestamp_ms <= self.last_timestamp_ms:
    timestamp_ms = self.last_timestamp_ms + 1
self.last_timestamp_ms = timestamp_ms
```

### 3. Preservação de FourCC para a PlayStation 4 Camera
O driver da PS4 Camera (OV580) expõe vídeo em YUY2/NV12. Forçar `'MJPG'` em câmeras PS Camera quebra a negociação DirectShow do Windows. Use a flag `is_pscam`:
```python
if target_fps >= 50 and not is_pscam:
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
```

### 4. Contrato Binário de 344 Bytes da Memória Compartilhada
O arquivo mapeado `Local\LegacyWebcamKinectPose` deve ter exatamente **344 bytes** e o protocolo seqlock deve alternar entre ímpar durante escrita e par ao finalizar.

---

## 🧪 Procedimento de Testes e Validação Obrigatória

Antes de aprovar qualquer modificação de código, execute a suíte de testes integrada:

```powershell
python LegacyPSCam_Sensor/test_suite.py
```

A suíte cobre 9 áreas fundamentais:

| Teste | Módulo Testado | Critério de Sucesso |
|---|---|---|
| `test_project_structure` | `sensor/`, `ui/`, `assets/` | Integridade da estrutura modular, dual-engine GUI (`LegacySensorQtGUI` e `LegacySensorTkGUI`), `launch_app`, assets e instanciação offscreen Qt6. |
| `test_config` | `sensor/config_manager.py` | Leitura, escrita, persistência e parsing de presets de resolução/FPS. |
| `test_shared_memory` | `sensor/kinect_shared_memory.py` | Tamanho exato de 344 bytes, paridade seqlock, máscara e pacer de 33ms do Kinect10.dll. |
| `test_hand_anchor` | `sensor/pose_filters.py` | Extrapolação correta do antebraço em coordenadas 3D e 2D. |
| `test_adaptive_smoother` | `sensor/pose_filters.py` | Alpha baixo para jitter em repouso (< 0.002) vs alpha alto em alta velocidade (> 0.5). |
| `test_calibrator` | `sensor/pose_filters.py` | Validação de eixos do Kinect: `ShoulderRight` positivo no X e `ShoulderLeft` negativo no X. |
| `test_pose_tracker` | `sensor/pose_tracker.py` | Rajada de 5 frames com intervalo < 1ms sem disparar exceção de timestamp. |
| `test_overlay` | `sensor/tracking_overlay.py` | Renderização do HUD, silhueta e esqueleto sem falhas numpy. |
| `test_camera_manager` | `sensor/camera_manager.py` | Snapshot PnP ultrarrápido (< 3ms via `cfgmgr32.dll`), máquina de estados da PS4 Camera, enumeração OpenCV, leitor prioritário `FrameBusReader`, detecção rápida de quadro preto e auto-crop de stereo Side-by-Side. |

### Adicionando Novos Testes
Ao criar novos recursos (como um novo algoritmo de suavização ou novo controle de GUI), adicione uma função `test_<funcionalidade>()` no arquivo `test_suite.py` e inclua sua execução na função principal `run_all_tests()`.

---

## 🚀 Como Implementar Novas Funcionalidades com Segurança

### Exemplo: Adicionar um Novo Preset de Resolução para a PS4 Camera
1. Abra `config_manager.py`.
2. Adicione a nova resolução na lista `PRESETS_PSCAM`:
   ```python
   PRESETS_PSCAM = [
       "1280x800 @ 60 FPS",
       "640x400 @ 120 FPS",  # Novo preset de altíssima velocidade
       ...
   ]
   ```
3. A função `parse_preset()` fará o parsing automático para `(640, 400, 120)`.
4. O `camera_manager.py` tentará negociar essa taxa com o DirectShow do PSCam4Win.
5. Atualize o arquivo `docs/FEATURES.md` documentando o novo preset.
6. Execute `python LegacyPSCam_Sensor/test_suite.py` para validar.
