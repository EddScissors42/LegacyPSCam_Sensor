# 🛠️ Guia de Instalação e Configuração — Legacy PSCam Sensor

Este documento apresenta o passo a passo completo para preparar o ambiente, instalar dependências, configurar o driver da **PlayStation 4 Camera**, vincular a DLL ao jogo **Just Dance PC** e executar a aplicação.

---

## 📋 Pré-Requisitos do Sistema

- **Sistema Operacional:** Windows 10 ou Windows 11 (64-bit).
- **Python:** Python 3.10 ou superior (recomendado Python 3.12 ou 3.15 de 64-bit).
- **Portas USB:**
  - Para Webcams comuns: Porta USB 2.0 ou superior.
  - Para **PlayStation 4 Camera:** **Porta USB 3.0 (azul) obrigatória**, pois o sensor duplo da PS4 Camera requer a largura de banda total do USB 3.0 para alimentar o stream de 60 FPS.
- **Espaço em Disco:** Menos de 150 MB (contra os 632 MB da versão original).

---

## 1. Instalação das Dependências Python

Abra o prompt de comando (PowerShell ou CMD) na pasta do projeto e execute:

```powershell
python -m pip install -r requirements.txt
```
*(Ou manualmente: `python -m pip install opencv-python mediapipe numpy Pillow`)*

> [!NOTE]
> As bibliotecas `tkinter`, `mmap`, `struct`, `json`, `threading` e `subprocess` já fazem parte da biblioteca padrão do Python e não requerem instalação via pip.

---

## 2. Configuração da PlayStation 4 Camera (PS4 Camera)

A PlayStation 4 Camera (modelos CUH-ZEY1 e CUH-ZEY2 com conector AUX modificado ou adaptador USB 3.0) precisa do driver em modo usuário **PSCam4Win** para carregar seu firmware e expor a câmera virtual no Windows.

### Passo 2.1 — Conectar a Câmera
1. Conecte a PS4 Camera em uma porta **USB 3.0** nativa do computador.
2. Ao plugar pela primeira vez, o Windows a identificará inicialmente como um dispositivo bootloader (`USB\VID_05A9&PID_0580`).

### Passo 2.2 — Instalar o Driver PSCam4Win
O instalador oficial já está incluído na pasta `tools/`:
1. Execute o arquivo [`tools/PSCam4Win-Setup.exe`](../tools/PSCam4Win-Setup.exe) (ou clique no botão **"Instalar Driver"** diretamente na interface do Legacy PSCam Sensor).
2. Conclua o assistente de instalação. Ele copiará os binários para `C:\Program Files\PSCam4Win`, registrará a DLL de câmera virtual e criará a inicialização automática em segundo plano.
3. Após a inicialização do driver, a PS4 Camera receberá o firmware e aparecerá no Gerenciador de Dispositivos como **`USB Camera-OV580`** (`VID_05A9&PID_058B`).

---

## 3. Configuração do Just Dance PC (Kinect Bridge)

Para que o jogo Just Dance PC consiga ler os movimentos gerados pelo simulador:

1. Localize a pasta `Kinect for Legacy DLL/` dentro de `LegacyPSCam_Sensor/`.
2. Copie o arquivo **`Kinect10.dll`**.
3. Abra a pasta raiz da sua instalação do **Just Dance PC** (onde fica o executável do jogo, por exemplo `JustDance.exe` ou a pasta do Legacy Offline).
4. Cole o `Kinect10.dll` na pasta do jogo, substituindo o existente se solicitado.

> [!TIP]
> Dentro do menu do Legacy PSCam Sensor há um atalho conveniente: clique no botão **"📁 Abrir Pasta do Kinect10.dll"** para abrir a pasta de origem imediatamente no Windows Explorer.

---

## 4. Executando a Aplicação

Dê um duplo-clique no executável nativo do projeto:
```cmd
LegacySensor.exe
```
*(ou se preferir, execute `INICIAR_SENSOR.bat`)*

- Abre o menu visual escuro instantaneamente, sem nenhuma janela de console/terminal.
- Permite alternar entre **PlayStation Camera** e **Webcam Padrão**.
- Permite escolher a resolução e taxa de quadros (ex: `1280x800 @ 60 FPS`).
- Ajusta a sensibilidade do rastreador e calibração de altura.
- Clique em **`▶ INICIAR RASTREAMENTO`** para iniciar a captura.

### Linha de Comando (CLI Avançada)
Você também pode iniciar via terminal passando parâmetros específicos:

```powershell
# Iniciar com a PS4 Camera no preset padrão
python main.py --mode pscam

# Iniciar forçando o uso de uma webcam específica (ex: índice 0)
python main.py --mode webcam --camera 0
```

---

## 5. Permissões de Usuário e Inicialização do Driver (Sem Modo Administrador)

Por padrão, o executável do driver PSCam4Win (`PSCam4WinTray.exe`) possui uma flag interna em seu manifesto exigindo privilégios de Administrador. Se o **Legacy PSCam Sensor** for aberto como usuário padrão (sem "Executar como Administrador"), o Windows anteriormente retornava o erro `[WinError 740] A operação solicitada requer elevação`.

### Soluções e Workarounds Nativos:
1. **Camada de Compatibilidade Automática (`RunAsInvoker` — Padrão do Sensor):**
   - O código do Legacy PSCam injeta automaticamente `__COMPAT_LAYER = 'RunAsInvoker'` ao disparar o driver. O Windows ignora a exigência de elevação do manifesto e inicializa o PSCam4Win com as credenciais do seu usuário normal, **sem necessidade de rodar o Legacy PSCam como administrador e sem janelas do UAC**.
2. **Fallback com ShellExecute (`runas`):**
   - Se o sistema bloquear a injeção de compatibilidade por diretiva, o sensor recorre à API `ShellExecuteW("runas")`, que solicita a confirmação do UAC **exclusivamente para o driver**, mantendo o Legacy PSCam sem privilégios elevados.
3. **Workaround Silencioso (Agendador de Tarefas do Windows):**
   - Para inicialização 100% silenciosa com privilégios elevados permanentes, você pode criar uma tarefa no Agendador do Windows com o nome `PSCam4Win` marcada com *"Executar com privilégios mais altos"*. Qualquer processo pode acioná-la via `schtasks /run /tn "PSCam4Win"`.
4. **Iniciar com o Windows (Recomendado):**
   - Configure o PSCam4Win para iniciar junto com o Windows (na pasta `shell:startup` ou Registro de inicialização). Dessa forma, o driver já estará pronto na bandeja do sistema sempre que você abrir o Legacy PSCam Sensor.

---

## 6. Como Jogar no Just Dance PC

1. Com o rastreador ativo (janela com esqueleto e contadores de FPS visível), abra o **Just Dance PC**.
2. Na tela de seleção de controle do jogo, escolha a opção **Kinect Sensor**.
3. O jogo detectará imediatamente o simulador através da memória compartilhada `Local\LegacyWebcamKinectPose`.
4. Posicione-se em frente à câmera a uma distância de aproximadamente **1,8 a 2,5 metros** para que todo o seu corpo (da cabeça aos tornozelos) fique visível.
5. Selecione sua música e dance! O esqueleto responderá a cada movimento e pontuará no jogo.
