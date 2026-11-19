# 🔌 Especificação da API e Protocolos IPC — Legacy PSCam Sensor

Como o **Legacy PSCam Sensor** opera como um simulador de dispositivo de hardware em tempo real para o jogo **Just Dance PC**, sua API principal consiste no **contrato binário de comunicação entre processos (IPC)** via memória compartilhada do Windows, na **interface da DLL proxy do Kinect** e na **interface de linha de comando (CLI)**.

---

## 1. Interface de Memória Compartilhada (Kinect Shared Memory IPC)

O jogo Just Dance PC lê continuamente as coordenadas do esqueleto humano através de um arquivo mapeado na memória virtual do Windows com nome fixo.

### Metadados da Conexão
- **Identificador (Tag):** `Local\LegacyWebcamKinectPose`
- **Mecanismo:** Windows Paging File Anonymous Mapped Memory (`mmap.mmap(-1, 344, tagname=...)`)
- **Tamanho Total:** Exatamente **344 bytes** (estrito, sem padding adicional)
- **Endianness:** Little-Endian (padrão x86 / x64 do Windows)

---

### Estrutura do Cabeçalho (Header) — 24 Bytes

O cabeçalho possui o formato binário `<IIIIQ`:

| Offset (Bytes) | Campo | Tipo C | Formato Python | Descrição |
|---|---|---|---|---|
| `0x00 - 0x03` | `magic` | `uint32_t` | `<I` | Constante mágica de identificação: `0x3150444A` (`'JDP1'`). |
| `0x04 - 0x07` | `version` | `uint32_t` | `<I` | Versão do protocolo de dados: sempre `1`. |
| `0x08 - 0x0B` | `seq` | `uint32_t` | `<I` | Número de sequência do protocolo seqlock (veja seção 1.2). |
| `0x0C - 0x0F` | `tracked` | `uint32_t` | `<I` | `1` se o jogador estiver detectado e rastreado; `0` se não houver corpo. |
| `0x10 - 0x17` | `timestamp_ms` | `uint64_t` | `<Q` | Timestamp Unix em milissegundos da captura do frame. |

---

### Estrutura dos Joints (20 Articulações) — 320 Bytes

Após o cabeçalho de 24 bytes, seguem-se sequencialmente as 20 articulações corporais do Kinect v1. Cada articulação possui **16 bytes** no formato `<ffff`:

```
Offset 0x18 + (JointIndex * 16):
├── float32 X     (4 bytes) - Coordenada lateral em metros (-1.0 a +1.0)
├── float32 Y     (4 bytes) - Coordenada vertical em metros (-1.0 a +1.0)
├── float32 Z     (4 bytes) - Coordenada de profundidade em metros (~2.0m)
└── float32 Conf  (4 bytes) - Confiança do rastreamento (1.0 = ótimo, 0.0 = perdido)
```

#### Tabela de Índices das 20 Articulações do Kinect v1:
| Índice | Nome do Joint | Descrição Anatômica |
|:---:|---|---|
| **0** | `HipCenter` | Centro da bacia (ponto de origem do esqueleto) |
| **1** | `Spine` | Coluna vertebral (ponto médio entre bacia e ombros) |
| **2** | `ShoulderCenter` | Base do pescoço / centro das clavículas |
| **3** | `Head` | Topo da cabeça / nariz |
| **4** | `ShoulderLeft` | Ombro esquerdo |
| **5** | `ElbowLeft` | Cotovelo esquerdo |
| **6** | `WristLeft` | Pulso esquerdo |
| **7** | `HandLeft` | Extremidade da mão esquerda |
| **8** | `ShoulderRight` | Ombro direito |
| **9** | `ElbowRight` | Cotovelo direito |
| **10** | `WristRight` | Pulso direito |
| **11** | `HandRight` | Extremidade da mão direita |
| **12** | `HipLeft` | Quadril esquerdo |
| **13** | `KneeLeft` | Joelho esquerdo |
| **14** | `AnkleLeft` | Tornozelo esquerdo |
| **15** | `FootLeft` | Ponta do pé esquerdo |
| **16** | `HipRight` | Quadril direito |
| **17** | `KneeRight` | Joelho direito |
| **18** | `AnkleRight` | Tornozelo direito |
| **19** | `FootRight` | Ponta do pé direito |

---

### 1.2 Canais de Imagem e Silhueta (`JMI1` e `JMI2` — 1.305.632 Bytes cada)

O jogo Just Dance PC consome a imagem da câmera e a máscara de profundidade do jogador através de canais de memória mapeada do Windows para compor o HUD da dança e a silhueta ("sombrinha") do jogador no canto inferior da tela e na seleção de dançarinos.

O `Kinect10.dll` implementa suporte duplo e busca primeiro o canal **V2 (`JMI2`)**, retrocedendo para o canal **V1 (`JMI1`)** se V2 não existir. O `LegacyPSCam_Sensor` alimenta ambos simultaneamente:

#### Canal V1: `Local\LegacyWebcamKinectImage` (JMI1)
- **Identificador (Tag):** `Local\LegacyWebcamKinectImage`
- **Tamanho Total:** Exatamente **1.305.632 bytes** (`0x13EC20`)
- **Estrutura do Cabeçalho (32 bytes):** `<IIIIIIQ`
  - `magic` (uint32): `0x31494D4A` (`'JMI1'`)
  - `version` (uint32): `1`
  - `seq` (uint32): Sequência seqlock (ímpar durante escrita, par após conclusão)
  - `tracked` (uint32): `1` se dançarino presente, `0` se ausente
  - `width` (uint32): `640`
  - `height` (uint32): `480`
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Payload 1 — Frame BGRA (1.228.800 bytes):**
  - Matriz de 640x480 pixels em formato `BGRA` (4 bytes por pixel), espelhado quando `mirror=True`.
- **Payload 2 — Máscara de Jogador (76.800 bytes):**
  - Matriz de 320x240 pixels em formato `uint8`. **Atenção:** O `Kinect10.dll` testa estritamente `byte >= 0x40` (64 em decimal) para classificar o pixel como Jogador 1. Pixels do corpo utilizam valor **`255`**; fundo contém valor **`0`**.

#### Canal V2: `Local\LegacyWebcamKinectImageV2` (JMI2)
- **Identificador (Tag):** `Local\LegacyWebcamKinectImageV2`
- **Tamanho Total:** Exatamente **1.305.632 bytes** (`0x13EC20`)
- **Estrutura do Cabeçalho (32 bytes):** `<IIIIIIQ`
  - `magic` (uint32): `0x32494D4A` (`'JMI2'`)
  - `version` (uint32): `2`
  - `seq` (uint32): Sequência seqlock
  - `tracked_mask` (uint32): Máscara de bits de jogadores ativos (bit 0 = Jogador 1 ativo)
  - `width` (uint32): `640`
  - `height` (uint32): `480`
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos
- **Payload 1 — Frame BGRA (1.228.800 bytes):** Idêntico ao canal V1.
- **Payload 2 — Player Index Mask (76.800 bytes):**
  - Matriz de 320x240 pixels em formato `uint8`. Pixels do Jogador 1 contêm valor `1`; fundo contém valor `0`.


---

### 1.3 Canal de Posição do Coach (`Local\LegacyWebcamKinectCoachX` — 28 Bytes)

- **Identificador (Tag):** `Local\LegacyWebcamKinectCoachX`
- **Tamanho Total:** **28 bytes**
- **Estrutura do Cabeçalho:** `<IIIIfQ`
  - `magic` (uint32): `0x3143584A` (`'JXC1'`)
  - `version` (uint32): `1`
  - `seq` (uint32): Sequência seqlock
  - `enabled` (uint32): `1` se ativo, `0` se desligado
  - `coachX` (float32): Coordenada horizontal relativa do coach
  - `timestamp_ms` (uint64): Timestamp Unix em milissegundos

> [!NOTE]
> No modo de rastreamento ao vivo, o campo `enabled` é mantido como `0` (`False`) porque o esqueleto gravado em `JDP1` e `JDP2` já contém o deslocamento lateral $X$ de seleção de dançarino. Ativar `enabled = 1` faria o `Kinect10.dll` somar `coachX` novamente via rotina `0x1020`, duplicando artificialmente o deslocamento lateral do jogador e projetando a cabeça para fora do enquadramento.

---

### Protocolo de Sincronização Seqlock (Lockless)

Para eliminar travamentos e deadlocks entre o Python (produtor dos dados) e o jogo Just Dance (consumidor dos dados), a comunicação utiliza a técnica de **Seqlock**:

1. **Escrita (Python):**
   ```python
   # 1. Torna a sequência ímpar antes de modificar os dados
   seq = (self.seq + 2) | 1
   shared_memory.seek(0)
   shared_memory.write(struct.pack('<IIIIQ', MAGIC, VERSION, seq, tracked, ts_ms))
   
   # 2. Escreve os 320 bytes dos 20 joints em lote único
   shared_memory.write(struct.pack(FULL_JOINTS_FMT, *flat_joints))
   
   # 3. Torna a sequência par após concluir a gravação
   seq += 1
   shared_memory.seek(8)
   shared_memory.write(struct.pack('<I', seq))
   shared_memory.flush()
   ```
2. **Leitura (`Kinect10.dll` no jogo):**
   - O jogo lê o valor de `seq` no offset 8.
   - Se `seq & 1 == 1` (ímpar), significa que o Python está gravando naquele instante. A DLL descarta a leitura e repete.
   - A DLL copia os 320 bytes para um buffer local.
   - A DLL lê novamente o valor de `seq`. Se o valor for idêntico ao lido no início, os dados são 100% consistentes e são repassados ao motor de pontuação do Just Dance.

---

## 2. Interface da DLL Proxy (`Kinect10.dll`)

A DLL proxy de 32 bits fornecida em `Kinect for Legacy DLL/Kinect10.dll` intercepta as seguintes 8 funções da API oficial da Microsoft do Kinect SDK v1.x:

```c
// Exportações de funções da Kinect10.dll consumidas pelo Just Dance PC
HRESULT WINAPI NuiCreateSensorById(const OLECHAR* strInstanceId, INuiSensor** ppNuiSensor);
HRESULT WINAPI NuiCreateSensorByIndex(int index, INuiSensor** ppNuiSensor);
int     WINAPI NuiGetSensorCount(int* pCount);
HRESULT WINAPI NuiImageGetColorPixelCoordinatesFromDepthPixel(eResolution, pView, lDepthX, lDepthY, usDepthValue, plColorX, plColorY);
HRESULT WINAPI NuiSetDeviceStatusCallback(NuiStatusProc callback, void* pUserData);
void    WINAPI NuiShutdown();
HRESULT WINAPI NuiSkeletonGetNextFrame(DWORD dwMillisecondsToWait, NUI_SKELETON_FRAME* pSkeletonFrame);
HRESULT WINAPI NuiSkeletonSetTrackedSkeletons(DWORD* pTrackingIDs);
```

- A função crítica é `NuiSkeletonGetNextFrame`: é nela que o jogo solicita o próximo quadro de esqueleto a cada tick de renderização. A DLL lê a memória compartilhada `Local\LegacyWebcamKinectPose`, preenche a estrutura `NUI_SKELETON_FRAME` e retorna `S_OK`.

### 2.1 Pacer Loop e Sincronização a 30 FPS na `Kinect10.dll`

Quando o jogo inicializa o rastreamento via `NuiSkeletonTrackingEnable` ou abre um stream de imagem via `NuiImageStreamOpen`, a `Kinect10.dll` inicia uma thread de ritmo em `0x10002320` para pulsar tanto o evento do esqueleto (`0x1001e96c`) quanto os eventos dos streams de vídeo/profundidade (`stream.hNextFrameEvent`):

- **Cadência Obrigatória de 30 FPS do Kinect v1:**
  - O motor de pontuação do Just Dance PC (avaliação de gestos, cálculo de velocidade das articulações e sincronização com o mapa de batidas da música) foi projetado estritamente para o hardware do Kinect v1, cuja taxa nativa é **30 FPS fixos** (`NUI_SKELETON_FRAME_RATE = 30`).
  - Se a thread for acelerada para 60 FPS (15 ms), o motor de dança recebe o dobro de quadros de esqueleto, perde a sincronia temporal com a música e marca **todas as jogadas como "X" (erro)**.
  - Portanto, a `Kinect10.dll` **deve obrigatoriamente** manter a cadência padrão de 33 ms (`0x10002346: push 0x21; call Sleep`).
- **Otimização de Timer no Python (Solução Real para os ~20 FPS):**
  - O motivo de o jogo parecer rodar em ~20 FPS com a DLL padrão em sistemas sem otimização é o agendador padrão do Windows (tick de 15,625 ms). Como 33 ms > 31,25 ms, o Windows adormecia a thread por 3 ticks (46,875 ms = **21,33 FPS**).
  - O `LegacyPSCam_Sensor` resolve isso sem tocar no binário da DLL: ao ativar `winmm.timeBeginPeriod(1)` e `ntdll.NtSetTimerResolution(10000, 1, ...)` no [tracking_session.py](file:///C:/Users/reydn/OneDrive/Documents/Projetos/LegacyPSCam_Sensor/tracking_session.py), a precisão do Windows vai para 1,0 ms. O `Sleep(33)` da DLL agora acorda pontualmente a cada **33,6 ms (30 FPS cravados)**, proporcionando o máximo de fluidez visual permitido pela engine do Just Dance mantendo 100% da pontuação perfeita.

---

## 3. Interface de Linha de Comando (CLI API)

O arquivo `main.py` aceita os seguintes parâmetros de execução:

```powershell
python main.py [--start] [--mode {pscam,webcam,ds4}] [--camera <int>]
```

### Argumentos:
- `--start`: Pula a exibição da interface gráfica Qt 6 e inicia o rastreamento imediatamente com a última configuração salva.
- `--mode {pscam,webcam,ds4}`: Força o modo de entrada:
  - `pscam`: Seleciona as otimizações para a PlayStation 4 Camera (60 FPS, YUY2/NV12).
  - `webcam`: Seleciona as otimizações para webcams convencionais (30/60 FPS DirectShow).
  - `ds4`: Inicia o modo de controle sem fio/USB DualShock 4 (IMU 500+ Hz via Virtual Phone).
- `--camera <int>`: Define o índice numérico do dispositivo de vídeo a ser aberto pelo OpenCV (`0`, `1`, etc.).

---

## 4. API Programática dos Módulos Python

Para desenvolvedores que importam os módulos internamente:

### `camera_manager.CameraManager` & `LatestFrameCamera`
- `CameraManager.is_pscam_installed() -> bool`: Retorna se o driver WinUSB da PS4 Camera está instalado/ativo (ou fallback legado).
- `CameraManager.is_pscam_running() -> bool`: Retorna se o backend nativo WinUSB está operacional.
- `CameraManager.initialize_ps4_camera() -> Tuple[bool, str]`: Verifica/instala o pacote INF WinUSB e faz o upload automático do firmware OV580 caso a câmera esteja em modo bootloader (`05A9:0580`).
- `CameraManager.enumerate_cameras(max_probe: int = 6) -> List[CameraInfo]`: Retorna a lista de câmeras conectadas cruzando índices com nomes PnP e interfaces WinUSB.
- `LatestFrameCamera(camera_index, target_w=640, target_h=480, target_fps=30, mirror=True, is_pscam=False, orientation=0, ps4_eye="right", ps4_backend_mode="native")`: Capturador assíncrono que utiliza `PS4CameraBackend` nativo quando `is_pscam=True`.
- `LatestFrameCamera.set_eye(eye: str)`: Alterna em tempo real entre `"right"` (Olho Direito, padrão) e `"left"` (Olho Esquerdo).
- `LatestFrameCamera.read_left_eye() -> Optional[np.ndarray]`: Retorna o frame BGR sincronizado do Olho Esquerdo (com rotação de orientação aplicada) sem reconverter o Olho Direito a partir de YUY2.
- `LatestFrameCamera.read_stereo(only_new: bool = False) -> Optional[dict]`: Retorna simultaneamente os frames BGR e YUY2 de ambos os olhos (`right_bgr`, `left_bgr`, `right_yuy2`, `left_yuy2`, `pts`, `timestamp_ms`, `seq`), reutilizando o buffer BGR já convertido do olho ativo.

### `sensor.ps4_backend` — Backend Nativo WinUSB para PlayStation 4 Camera
- `PS4FirmwareManager`:
  - `locate_valid_firmware() -> Optional[bytes]`: Localiza e valida criptograficamente `firmware.bin` (`68.032` bytes, SHA-1 `8b8a6621d358f6782c2e3b31aac2cdfb25102c00`, SHA-256 `09513d10...`) em `%ProgramData%\LegacySensor\Firmware\`.
  - `ensure_firmware(allow_download: bool = True) -> Optional[bytes]`: Garante a presença do firmware validado em disco, baixando via HTTPS caso ausente.
  - `upload_to_bootloader_device(allow_download: bool = True, wait_reenumerate_s: float = 6.0) -> Tuple[bool, str]`: Envia o firmware em blocos de 512B ao dispositivo `05A9:0580`, dispara o comando de reboot (`0x5B`) e aguarda a re-enumeração como `05A9:058B`.
- `PS4UsbDevice`:
  - `probe_hardware_status() -> dict`: Inspeciona o estado PnP e WinUSB da câmera (`READY`, `BOOTLOADER_UPLOADING`, `DRIVER_MISSING`, `DISCONNECTED`).
  - `open(target_w=1280, target_h=800, target_fps=60) -> bool`: Abre as interfaces WinUSB 0 (VideoControl) e 1 (VideoStreaming Alt 1), negocia Probe/Commit UVC YUY2 e ativa Auto-Exposure (`CT_AE_MODE_CONTROL = 0x02`) e Anti-Flicker 60Hz.
- `PS4CameraBackend`:
  - `start() -> bool` / `stop() -> None`: Inicia e encerra o anel isócrono de 8 URBs Overlapped (`WinUsb_ReadIsochPipeAsap`) no endpoint `0x81`.
  - `read_frame(only_new: bool = False) -> Optional[np.ndarray]`: Retorna o frame BGR do olho selecionado (`"right"` por padrão).
  - `read_left_frame() -> Optional[np.ndarray]`: Converte sob demanda apenas o plano YUY2 do Olho Esquerdo para BGR (eliminando conversão duplicada do Olho Direito no modo de Visão Estéreo).
  - `read_stereo_frames(only_new: bool = False) -> Optional[dict]`: Retorna ambos os fluxos ópticos sincronizados reutilizando o buffer `_selected_bgr` do olho ativo.
- `PS4DriverInstaller`:
  - `verify_driver_status() -> dict`: Verifica sem elevação UAC se `legacy_pscam_device.inf` está instalado e associado ao `WinUSB.sys` (incluindo disponibilidade do instalador de fallback assinado `fallback_installer_present`).
  - `get_fallback_installer_path() -> Optional[Path]`: Localiza o instalador assinado de fallback `tools/PSCam4Win-Setup.exe`.
  - `install_or_repair_driver(force_reinstall: bool = False, allow_fallback_installer: bool = True) -> Tuple[bool, str]`: Solicita elevação pontual via `pnputil.exe` apenas quando necessário e aciona automaticamente o instalador de fallback caso a política de assinatura digital do Windows rejeite um catálogo INF não assinado.

### `pose_tracker.PoseTracker`
- `PoseTracker(model_path=None, detection_confidence=0.5, smoothing_alpha=0.55, target_height_m=1.75, cfg=None, model_variant=None)`: Construtor do motor de IA (`model_variant` aceita `"lite"`, `"full"` ou `"heavy"`).
- `PoseTracker.process_frame(frame: np.ndarray, mirror: bool = False) -> Tuple[bool, List[Tuple], List[Tuple], Optional[np.ndarray]]`: Processa o quadro bruto, executa Hand Anchor, suavização EMA, calibração de esqueleto e gera a máscara de segmentação anatômica. Retorna `(sucesso, kinect_joints, pixel_joints, body_mask)`.
- `PoseTracker.build_body_mask(norm_landmarks, width, height) -> np.ndarray`: Gera a máscara binária 2D do corpo do jogador a partir dos landmarks.
- `PoseTracker.reset_filters()`: Limpa o estado interno dos filtros de suavização após perda de rastreamento.

### `kinect_shared_memory.KinectBridge`
- `KinectBridge()`: Inicializa e unifica os três canais IPC (`Local\LegacyWebcamKinectPose`, `Local\LegacyWebcamKinectImage` e `Local\LegacyWebcamKinectCoachX`).
- `KinectBridge.write(joints, frame_bgr, mask_binary, tracked=True) -> bool`: Grava atomicamente as articulações no canal `JDP1` e o frame BGRA + máscara de profundidade no canal `JMI1`.
- `KinectBridge.write_empty() -> bool`: Notifica o jogo de que não há jogador rastreado.
- `KinectBridge.close()`: Fecha e desaloca todos os blocos de memória mapeada com segurança.

### `kinect_shared_memory.KinectSharedMemory`
- `KinectSharedMemory(tagname: str = "Local\\LegacyWebcamKinectPose")`: Inicializa o buffer de pose de 344 bytes.
- `KinectSharedMemory.write_pose(joints, tracked: bool = True)`: Grava as 20 articulações no formato binário `<IIIIQ` + `<ffff` * 20.

### `kinect_shared_memory.KinectImageSharedMemory`
- `KinectImageSharedMemory(tagname: str = "Local\\LegacyWebcamKinectImage")`: Inicializa o buffer de imagem de 1.305.632 bytes.
- `KinectImageSharedMemory.write_image_and_mask(frame_bgr, mask_binary, tracked: bool = True)`: Converte e grava o frame BGRA 640x480 e a máscara de profundidade 320x240 para o HUD do jogo.

---

## 5. Esquema de Configuração (`config.json`)

As preferências do usuário são persistidas em `config.json` via `ConfigManager`:

```json
{
  "camera_mode": "pscam",
  "camera_index": 0,
  "ps4_camera_backend": "native",
  "ps4_eye": "right",
  "pscam_preset": "1280x800 @ 60 FPS",
  "webcam_preset": "640x480 @ 30 FPS",
  "mirror_horizontal": true,
  "tracking_preset": "balanced",
  "pose_model": "full",
  "smoothing_alpha": 0.55,
  "detection_confidence": 0.5,
  "target_height_m": 1.75,
  "auto_calibrate": true,
  "launch_pscam_tray": true,
  "show_hud": true
}
```

- `ps4_camera_backend`: Backend de captura para a PlayStation 4 Camera (`"native"` para WinUSB direto, `"pscam4win"` para fallback legado).
- `ps4_eye`: Sensor óptico ativo da PlayStation 4 Camera (`"right"` como padrão para o Olho Direito, `"left"` para o Olho Esquerdo).
- `tracking_preset`: Perfil ativo selecionado no menu (`"balanced"`, `"competitive"`, `"stable"` ou `"custom"`).
- `smoothing_alpha`: Coeficiente de suavização EMA (0.20 a 0.85).
- `detection_confidence`: Limiar mínimo de confiança da IA MediaPipe (0.30 a 0.80).
- `target_height_m`: Escala métrica alvo interna (1.75m) mantida constante pelo `SkeletonCalibrator`.

---

## 6. Interface de Linha de Comando (CLI)

O ponto de entrada `main.py` aceita argumentos de linha de comando para controle direto:

```powershell
python main.py [-h] [--start] [--mode {pscam,webcam,ds4}] [--camera CAMERA]
```

| Argumento | Opções | Padrão | Descrição |
|---|---|---|---|
| `--start` | Flag booleana | `False` | Inicia a sessão de rastreamento diretamente sem abrir a interface gráfica. |
| `--mode` | `pscam`, `webcam`, `ds4` | Configurado em `config.json` | Força o modo de sensor/controle a ser utilizado. |
| `--camera` | Inteiro (`0`, `1`, ...) | Configurado em `config.json` | Força o índice da câmera de captura no OpenCV. |

---

## 7. Pacote de Interface Gráfica (`ui`)

O pacote `ui` expõe uma interface modular baseada exclusivamente em **PySide6 (Qt 6)**:

- `ui.launch_app() -> int`: Inicializador principal da interface gráfica Qt 6 (`PySide6`).
- `ui.LegacySensorQtGUI`: Janela principal baseada em PySide6 / Qt 6, com detecção de hotplug por sinais Qt e balão contextual de estado de hardware.
- `ui.LegacySensorGUI`: Alias padrão para `LegacySensorQtGUI`.
- `ui.pages`: Exporta `UIPagesMixin` com os construtores declarativos das 4 páginas (`_build_video_view`, `_build_calib_view`, `_build_exp_view`, `_build_ds4_view`).
- `ui.widgets`: Exporta `pil_to_qpixmap`, `SlidingStackedWidget`, `DeviceNavCard` e `CalibPresetCard`.
- `ui.benchmark_dialog`: Exporta `TelemetryBenchmarkChart` e `TelemetryBenchmarkDialog`.
- `ui.HAS_QT -> bool`: Booleano que indica se o PySide6 está instalado e operacional.

---

## 8. Driver Bluetooth/USB HID do DualShock 4 e Compatíveis (`sensor.ds4_controller`)

Módulo nativo Windows HID (zero dependências) para leitura de alta taxa (500+ Hz) do controle DualShock 4 e gamepads compatíveis (Nível A) via Bluetooth ou cabo USB.

### Constantes e Estruturas de Descoberta
- `KNOWN_DS4_TARGETS: Dict[str, Tuple[str, ...]]`: Mapeamento de VIDs e PIDs conhecidos:
  - Sony (`054c`): `05c4` (V1), `09cc` (V2), `0ba0` (Dongle USB sem fio).
  - Hori (`0f0d`): `005e`, `0066`, `00ee`, `011c`.
  - Nacon (`146b`): `06cd`, `06e5`, `0d01`, `0d02`.
  - Razer (`1532`): `1000`, `1004`, `1007`, `1008`, `1009`, `100a` (Raiju Ultimate/Tournament).
  - Astro (`9886`): `0025` (C40 TR).
  - Scuf (`2e95`): `7725`, `9925` (Vantage / Impact).
  - Qanba (`2c22`): `2000`, `2300`, `2500`.
  - Mad Catz (`0738`): `5252`, `8250`, `8384`.
  - ShanWan (`2563`): `0575`, `0555`, `0523` (clones sem fio).
  - DragonRise (`0079`): `181b`, `181c`, `181d` (clones sem fio).
- `BLACKLISTED_DEVICE_VENDORS = ("045e",)`: Dispositivos explicitamente bloqueados (controles Microsoft Xbox sem giroscópio/acelerômetro).

### Funções e Classes Principais
- `find_ds4_devices(permissive: bool = True) -> List[str]`: Enumera as interfaces HID PnP do Windows sob a GUID `{4d1e55b2-f16f-11cf-88cb-001111000030}`. No modo estrito filtra por Sony (`0x054C`), e no modo permissivo aceita os alvos conhecidos e qualquer controle HID compatível (exceto Xbox).
- `is_compatible_ds4_path(path: str, permissive: bool = True) -> bool`: Valida se o caminho HID pertence a um dispositivo compatível.
- `detect_controller_name(path: str) -> str`: Identifica e retorna o nome amigável do modelo (ex.: `"Razer Raiju (PS4)"`, `"ShanWan DS4 Clone"` ou `"Generic / Clone DS4"`).
- `get_ds4_controller() -> DS4Controller`: Retorna a instância singleton do controlador.
- `DS4Controller.connect(device_path=None, permissive=None) -> bool`: Abre o handle Win32, realiza o handshake do Relatório Estendido 0x11 (se aplicável), detecta o nome do periférico, aciona vibração háptica de boas-vindas e inicia a thread de amostragem.
- `DS4Controller.disconnect() -> None`: Desativa a barra de luz e fecha o handle Win32 de forma segura.
- `DS4Controller.trigger_rumble(small, large, duration_sec) -> None`: Dispara um pulso háptico assíncrono.
- `DS4Controller.set_lightbar(r, g, b) -> None`: Altera a cor RGB da barra de luz LED.
- `DS4State`: Dataclass contendo:
  - `connected: bool`
  - `is_usb: bool`
  - `battery_pct: int`
  - `is_charging: bool`
  - `accel_g: Tuple[float, float, float]`
  - `gyro: Tuple[float, float, float]`
  - `buttons: Dict[str, bool]`
  - `sample_rate_hz: float`
  - `imu_frozen: bool`: Flag booleana que acusa quando a magnitude do acelerômetro é $< 0.05G$ por 50 leituras seguidas (sensor ausente ou sem envio pelo Bluetooth).
  - `controller_name: str`: Nome legível do controle conectado.

### Estrutura do Pacote Bluetooth Output Report 0x11 (78 Bytes)
- **Byte 0:** `0x11` (Report ID)
- **Byte 1:** `0xC0` (Streaming & flags)
- **Byte 3:** `0x07` (Habilita motores de rumble e LED lightbar)
- **Byte 6:** Motor pequeno de alta frequência (0..255)
- **Byte 7:** Motor grande de baixa frequência (0..255)
- **Bytes 8–10:** RGB da barra de luz LED
- **Bytes 74–77:** Checksum CRC-32 (IEEE 802.3) little-endian calculado sobre `bytes([0xA2]) + out_rep[0:74]`.

---

## 9. Celular Virtual e Auto-Detecção de Músicas (`sensor.virtual_phone`)

O módulo `sensor.virtual_phone` gerencia a comunicação com o Just Dance através do protocolo WebSocket `/smartphone` (v1/v2):

### Funções de Auto-Detecção de Processo e Música Ativa
- `find_just_dance_pids() -> List[int]`: Enumera os processos em execução via `CreateToolhelp32Snapshot` Win32 buscando instâncias de `jd2022.exe`, `jd2021.exe`, `jd2020.exe`, `jd2019.exe`, `jd2018.exe`, `jd2017.exe`, `justdance.exe` (latência ~0.5ms).
- `detect_active_song_from_game_process() -> str`: Varre páginas de dados privadas (`MEM_COMMIT`, ignorando `MEM_IMAGE` e páginas executáveis) do processo Just Dance com um buffer reutilizável pré-alocado de 1 MB para localizar a stream ativa `/map/<MapName>/...webm`. Converte o identificador do mapa (ex: `SmalltownBoy`) no título formatado da música (`Smalltown Boy`).
- `VirtualPhoneController.current_song`: Propriedade que retorna o nome da música ativa, executando a busca em memória sob demanda apenas quando a gravação de telemetria ou benchmark automático estiverem ativos (`auto_record_enabled` ou `_logging_enabled`), com intervalo mínimo de 2.5s.

### `sensor.virtual_phone.HandAccelerometer`
- `HandAccelerometer(hand="right", sensitivity=1.0)`: Converte as 20 articulacoes do Kinect em aceleracao 3D [ax, ay, az] compativel com o protocolo de pontuacao de smartphone do Just Dance.
  - **Filtro de Velocidade Pre-Derivada:** Filtro exponencial com tau = 45ms para supressao de ruido de segunda ordem.
  - **Escala de Forca G Calibrada:** Ganho calibrado contra ground truth de controle fisico DualShock 4 (Smalltown Boy).
  - **Teto Vetorial 3D:** Clamping de magnitude Euclidiana a 7.0G maximo.
  - **Convencao de Eixos:** Screen-relative (+Y ao longo do antebraco, +Z em direcao ao dancarino).

---

## 10. Motor de Visão Estéreo (`sensor.stereo_matcher`)

O pacote `sensor.stereo_matcher` implementa o pipeline óptico de visão estéreo para a PlayStation 4 Camera (sensores dual OV9713 e ponte OV580):

### 10.1 Constantes Ópticas
- `PS4_STEREO_BASELINE_M = 0.0852`: Distância física entre centros ópticos (85.2 mm).
- `NOMINAL_FOCAL_AT_1280 = 860.0`: Distância focal de referência em pixels a 1280x800 (HFOV ~73°).
- `STEREO_MODES`: `("disabled", "sparse_metric", "full_depth")`.

### 10.2 Classes Principais
- `StereoCalibrator(baseline_m=0.0852)`:
  - `update_resolution(w, h)`: Computa matrizes intrínsecas $K_1, K_2$, rotação $R$, translação $T = [B, 0, 0]^T$ e look-up tables `cv2.initUndistortRectifyMap`.
  - `rectify(left, right) -> (rect_left, rect_right)`: Aplica `cv2.remap` em $<0.8\text{ ms}$.
- `StereoDepthEngine(baseline_m=0.0852)`:
  - `triangulate_sparse_joints(rect_left, rect_right, joints_2d, search_radius_px=48, patch_half_size=6, vertical_tol_px=4) -> Dict[joint_id, (X, Y, Z, conf)]`:
    Executa busca em banda epipolar 2D no canal verde (`cv2.matchTemplate` com interpolação parabólica 2D) seguida de refinamento sub-pixel por Fluxo Óptico Piramidal Lucas-Kanade (`cv2.calcOpticalFlowPyrLK` em ROIs locais) em $<0.8\text{ ms}$, computando profundidade métrica $Z = \frac{f \cdot B}{d}$ e auto-calibrando dinamicamente o desalinhamento vertical entre as lentes (`vertical_offset_px`).
  - `compute_dense_depth_mask(rect_left, rect_right, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8, align_to_right=True) -> np.ndarray`:
    Calcula mapa de disparidade a 320x200 via `cv2.StereoSGBM_3WAY` (~2.5ms), gerando máscara binária uint8 (255 = zona do jogador, 0 = fundo/fora).
  - `compute_confirmed_background_mask(rect_left, rect_right, target_w=320, target_h=240, min_z_m=0.8, max_z_m=2.8, align_to_right=True) -> np.ndarray`:
    Identifica regiões positivamente confirmadas fora do envelope de profundidade do dançarino ($Z > \text{max\_z\_m}$ ou $Z < \text{min\_z\_m}$), alinhadas à lente direita.
