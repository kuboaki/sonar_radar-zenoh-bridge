# 手動デモ手順(ROSからstart/stopを注入する構成)

2026-08-04、SIM(Mac)をleader、実機(Pi4)をfollowerとして、Pi5の
`hakoniwa_pdu_ros`ブリッジ経由でROSからstart/stopを注入する構成を
実地検証した際の手順。ターミナルを新しく開くたびにvenvのactivateを
忘れがちなので、そのまま貼り付けて使えるように書き出したもの。

## 登場する機体とIP

| 機体 | 役割 | IP |
|---|---|---|
| Mac | SIM(leader)、zenohdルーター、Hakoniwa plant | 192.168.11.2 |
| Pi4(実機) | radar_base(follower) | 192.168.11.3 |
| Pi5 | hakoniwa_pdu_rosブリッジ(ROS⇔Zenoh中継) | 192.168.11.4 |

## 開くターミナル一覧

1. Mac: zenohd
2. Mac: Hakoniwa plant(MuJoCoビューア)
3. Mac: SIM(leader、run_hako.py)
4. Pi4: 実機(follower、demo_real_follower.bash)
5. Pi5: hakoniwa_pdu_rosブリッジ
6. Pi5(または5と同じ端末で使い回す): ROS start/stop注入コマンド

## 手順

### 1. Mac: zenohdを起動

```bash
cd ~/Projects/sonar_radar-zenoh-bridge/config/mac/zenohd
zenohd -c router.json5
```

すでに起動中なら不要(常駐インフラとして扱ってよい)。

### 2. Mac: Hakoniwa plantを起動

```bash
cd ~/Projects/hakoniwa-mujoco-robots
MJPYTHON="$(pwd)/.venv/bin/mjpython" bash run-hakopy.bash \
  ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer --debug
```

`'SonarRadarAsset' 登録完了。hako-cmd start を待機中...` の表示を待つ。

**【重要】この端末のビューアウィンドウが自動終了する(「シミュレーション終了を
検出→自動終了」と出る)と、その後の登録(手順3)が
`ERROR: Can not register asset` で失敗する。** そうなったらこの端末を
Ctrl-Cで止め、手順2をやり直すこと(この端末を`bridge/cleanup.bash`で
誤って巻き込んで止めてしまわないよう注意。plant/ビューアはcleanup.bashの
対象外だが、`mjpython`パターンには引っかかるので、他の端末で
`bash bridge/cleanup.bash`を実行するときはこの点に注意)。

venvの活性化は不要(`run-hakopy.bash`内部で`hakoniwa-mujoco-robots/.venv`
(Python 3.14)へ自動的に切り替わる)。

### 3. Mac: SIM(leader)を起動

**ROSからstart/stopを注入する運用のときは、demo_hako_leader.bashは
使わない**(あちらはMuJoCoビューアのSpaceキー操作を前提にした
`--hako-starter`版なので、ROS注入と役割が競合する)。代わりに
`demo_hako_follower.bash`を`LEADER=1`付きで起動する
(2026-08-04追加、下記「leaderの交換」参照)。

```bash
cd ~/Projects/sonar_radar-zenoh-bridge
LEADER=1 bash bridge/demo_hako_follower.bash
```

`'SonarRadarZenohBridgeController' 登録完了。hako-cmd start を待機中...`
の表示を待つ。venvの活性化はここも不要(`run-hakopy.bash`が内部で
`hakoniwa-mujoco-robots/.venv`への切り替えを行う)。

### 4. Mac: 別端末で`hako-cmd start`を実行

```bash
cd ~/Projects/hakoniwa-mujoco-robots
hako-cmd start
```

**これを実行するまで手順3のZenoh購読(broker.open())が開かない。**
実機側のstarterボタンやROSからのstart注入は、これより後にすること。

### 5. Pi4: 実機(follower)を起動

```bash
ssh kuboaki@192.168.11.3
cd ~/Projects/sonar_radar-zenoh-bridge
bash bridge/demo_real_follower.bash
```

`WAIT_FOR_START_PRESS`(黄緑色の表示)になるまで待つ。venvの活性化は
スクリプト内で自動化済み(2026-08-04修正、`bridge/demo_real_follower.bash`・
`demo_real_leader.bash`とも`.venv/bin/activate`を自動でsourceする)。

### 6. Pi5: hakoniwa_pdu_rosブリッジを起動

```bash
ssh ubuntu@192.168.11.4
cd ~/Projects/sonar_radar-zenoh-bridge
bash config/raspi5/run_ros_bridge.bash
```

`loaded 2 bindings from ...` の表示が出れば準備完了。Ctrl-Cで停止する
までフォアグラウンドで動き続ける。

### 7. Pi5: 別端末(またはCtrl+Zで一旦止めた6の端末)からstartを注入

```bash
ssh ubuntu@192.168.11.4
cd ~/Projects/sonar_radar-zenoh-bridge
bash config/raspi5/demo_ros_start.bash
```

SIM(手順3)・実機(手順5)の両方の端末で`SCANNING`への遷移が表示されれば
成功。停止するときは同様に:

```bash
bash config/raspi5/demo_ros_stop.bash
```

## leaderの交換

`demo_real_follower.bash`・`demo_hako_follower.bash`はどちらも既定では
follower(`--leader`なし)。ROSからstart/stopを注入する2台構成では、
どちらかが必ずleaderを持たないと誰もマーカー検出/反転をせずSCANNINGが
タイムアウトする(SCAN_FAILED)。`LEADER=1`環境変数を付けると、その場で
leader/follower役を交換できる:

```bash
# 実機をleaderにする場合(SIM側はLEADER無しでfollowerのまま)
LEADER=1 bash bridge/demo_real_follower.bash

# SIMをleaderにする場合(実機側はLEADER無しでfollowerのまま)
LEADER=1 bash bridge/demo_hako_follower.bash
```

starterは常に`--no-starter`のまま(ROS駆動なので、leader/followerどちらの
役でも物理starterは使わない)。origin番号も役割に関わらず固定
(実機=2、SIM=5)。

## 既知の注意点

- **実機とSIMの旋回速度差**: SIM(leader)の旋回速度・マーカー検出間隔と、
  実機(follower)のSCANNINGタイムアウト(8秒、ケーブル巻き込み防止のため
  実機は短め設定)が噛み合わず、実機側が`SCAN_FAILED`になることがある
  (2026-08-04に実地で確認)。バグではなく、実機・SIM混在構成特有の
  タイミング課題(メモリの「Follower position-sync design idea」参照、
  未着手)。`SCAN_FAILED`後は`TERMINATED`まで正常に到達し、モーターは
  確実に停止する(安全面は問題ない)。
- **起動順序**: キャリブレーション(手順3・5)自体はマシン間協調が無い
  ローカル処理なので、Mac・Pi4のどちらを先に起動してもよい。ただし
  手順4(`hako-cmd start`)より前にstart系のイベントを送っても、SIM側は
  まだ購読していないので取りこぼす。
- **Pi5のネットワーク**: Wi-Fi/有線LANを同時に外部接続できない環境の
  場合、`ssh ubuntu@192.168.11.4`自体はLAN内なので問題なく使えるが、
  `git pull`等のGitHubアクセスは有線LAN接続時のみ可能(詳細はdevelopment_log
  やメモリ参照)。
