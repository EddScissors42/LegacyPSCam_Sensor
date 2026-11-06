# Regra Especializada — Pipeline de Pose e Cinemática Kinect

Esta regra aplica-se a qualquer modificação em `pose_tracker.py`, `tracking_session.py` ou qualquer componente que processe landmarks do corpo humano.

---

## 1. Convenção de Coordenadas do Kinect v1

O jogo Just Dance PC espera coordenadas de articulação no espaço de câmera do Kinect v1:
- **Eixo X (Lateral):**
  - No Kinect original: Negativo à esquerda do sensor, Positivo à direita do sensor.
  - No MediaPipe World Landmark: Positivo para a esquerda da pessoa (sua direita olhando de frente), Negativo para a direita da pessoa.
  - **Regra de Conversão:** Deve-se **inverter o sinal do X** ao converter do MediaPipe para o Kinect:
    `k_x = -(world_x - origin_x) * scale`
  - Se esta inversão não for feita, os braços do jogador são invertidos na pontuação do Just Dance (uma mão direita levantada pontuará como mão esquerda no vazio, gerando MISS).
- **Eixo Y (Vertical):**
  - Positivo para cima, Negativo para baixo.
  - `k_y = -(world_y - origin_y) * scale` (já que o Y de câmera/imagem cresce para baixo).
- **Eixo Z (Profundidade):**
  - Centrado na distância nominal de dança de 2,0 metros:
    `k_z = 2.0 + (world_z - origin_z) * scale`

---

## 2. Separação Estrita de Inferência vs Exibição (Mirroring)

- **Regra Inquebrável:** NUNCA aplique `cv2.flip(frame, 1)` antes de chamar `pose_landmarker.detect_for_video()`.
- Se o frame for espelhado antes da rede neural, a IA vê a imagem espelhada e troca os rótulos anatômicos (`RIGHT_INDEX` vira `LEFT_INDEX`), quebrando todo o sistema de coach do Just Dance.
- **Padrão Correto:**
  1. Envie o frame bruto capturado diretamente para o MediaPipe.
  2. Extraia os 33 landmarks e monte as 20 articulações anatômicas.
  3. No momento de renderizar o HUD na tela, espelhe o frame para o usuário (`display_frame = cv2.flip(frame, 1)`) e espelhe as coordenadas 2D dos pontos desenhados (`px = w - 1 - px`).

---

## 3. Garantia de Timestamps Monotônicos (MediaPipe Video Mode)

- O MediaPipe Pose Tasks API em modo `RunningMode.VIDEO` exige que cada chamada consecutiva a `detect_for_video(mp_image, timestamp_ms)` tenha um `timestamp_ms` estritamente maior que o anterior.
- Em taxas elevadas (60 FPS ou mais) ou em câmeras assíncronas com buffer rápido, múltiplos frames podem ser despachados no mesmo milissegundo de relógio do sistema operacional.
- **Implementação Obrigatória:**
  ```python
  now_ms = int((time.time() - self.start_time) * 1000)
  timestamp_ms = max(now_ms, self.frame_index)
  if timestamp_ms <= self.last_timestamp_ms:
      timestamp_ms = self.last_timestamp_ms + 1
  self.last_timestamp_ms = timestamp_ms
  ```

---

## 4. Filtro Hand Anchor e Suavização Adaptativa

- **HandAnchorFilter:** Quando o usuário executa giros ou movimentos de alta velocidade, a confiança dos dedos (`LEFT_INDEX`, `RIGHT_INDEX`) pode oscilar. O filtro deve ancorar a mão extrapolando o vetor do antebraço (`cotovelo -> pulso`) por um comprimento médio (~0.12m em 3D, ~25px em 2D).
- **AdaptiveSmoother (EMA Sensível à Velocidade):**
  - Para movimentos lentos ou estáticos: Utilize alpha baixo (~0.25 a 0.35) para eliminar qualquer jitter ou tremedeira na pontuação.
  - Para movimentos rápidos: O alpha deve escalar dinamicamente até 0.85+ para garantir resposta imediata e latência zero em passos rítmicos.
  - Ao perder o rastreamento (`tracked = False`), limpe o histórico do suavizador para que a reaquisição do corpo seja instantânea e não arraste coordenadas antigas.
