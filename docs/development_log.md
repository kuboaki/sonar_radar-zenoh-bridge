# 開発ログ: テストによる段階的な開発

`docs/zenoh_state_machine_design.md` が「何を作るか」の記録だとすると、こちらは「どう作ったか」の記録。メッセージ接続を伴う分散システムでは、メッセージが実際に疎通しないと何も検証できないため、状態機械図の状態を1つずつ実装し、都度実際のメッセージング基盤(Zenoh)で動作確認しながら進めている。この進め方自体と、そこで得られた教訓をここに残す。

## 開発の進め方(方針)

- 状態機械図の最初の状態から、必要最小限のクラス・関数(に相当する関数)を作り、実際に動かして確認する
- 確認できたら次の状態の実装に進む、を繰り返す
- モックで済ませず、実際のメッセージング基盤(zenohd + hakoniwa_pdu_endpoint)を使って検証する
- デバッグ・観測用の処理は、対象システムの実装そのものに混ぜず、横断的関心事として分離する

## マイルストーン1: INIT 〜 WAIT_CALIBRATED (完了)

### 実装したもの

`bridge/spikehat_timer.py`, `broker.py`, `sonar_radar_app.py`, `run_calibration_smoke_test.py`, `watch_state.py`, `state_reporter.py`。詳細は `README.md` の「`bridge/` の動作確認」節を参照。

### 確認した内容

- 単一プロセス内の自己ループバックによる `calibrate` → `calibrated` → guard通過 → `WAIT_FOR_START_PRESS` 到達(成功経路)
- タイムアウト → `CALIBRATION_FAILED` → `TERMINATED`(失敗経路)
- 別プロセス(`watch_state.py`)からのリアルタイム状態観測(別ターミナル・ユーザー自身の手元での再現も含む)

### 得られた教訓

1. **観測用処理は状態機械の実装から外に出す。**
   当初 `broker.publish_state()` の呼び出しを `SonarRadarApp._transition_to()` の中に直接書いていたが、これは状態機械図に無い関心事を実装に混ぜ込むアンチパターンだった。指摘を受け、`run()` を外側からラップする `state_reporter.py` に切り出した。`sonar_radar_app.py` 自体は図に忠実な実装のみを保ち、「状態が変わったらレポートする」という繰り返し構造への付与は変換規則側の仕事として分離した。

2. **分散システムのデバッグでは、まず自分の診断ツール自体を疑う。**
   「別プロセス間でメッセージが届いていない」ように見えた問題は、実際にはZenoh配送は正常で、バックグラウンドプロセスの標準出力がバッファリングされたまま(`-u`なし・`flush=True`なし)、ログファイルを早すぎるタイミングで読んでいた、という検証コード側の不備だった。`-u`(unbuffered)で実行し、プロセスの終了を`wait`してからログを確認して判明した。

3. **環境差は、実装者本人が手元で再現して初めて見つかる場合がある。**
   macOSの `DYLD_LIBRARY_PATH` に `/usr/local/hakoniwa/lib`(以前の `sudo bash install.bash` で作られた、Zenoh無効の古いビルドが残っている場所)が含まれる環境だと、`HAKO_PDU_ENDPOINT_SHARED_LIB` で絶対パス指定していても、dyldが同名ファイルをそちらから優先して読み込んでしまう問題があった。この問題は作業環境(Bashツール側のシェル)では再現せず、ユーザー本人が実際に手元のターミナルで試して初めて発覚した。対処は `bridge/env.sh` で `.local` 側のパスを `DYLD_LIBRARY_PATH` の先頭に追加すること(共有のシステム領域 `/usr/local/hakoniwa/lib` 自体は変更しない)。

### 実機(Raspberry Pi 4B+) + Mac、2台構成での検証(完了・大きな進展)

単一プロセスの自己ループバックだけでは、`calibration_participants` が実質1個(自分自身)しかなく、「複数の異なるoriginが揃うのを待つ」というguardロジックの本質、すなわち前回の設計転回のきっかけになった問題そのものが検証できていなかった。そこで、マイルストーン1の範囲(キャリブレーションのみ)を、実機 `192.168.1.62` とMacの実ネットワーク越し2台構成で検証した。ブリッジ役(Raspberry Pi 5, `192.168.1.4`)は今回のスコープでは不要と判断し、対象から外した。

**事前調査でわかったこと**

- 実機の `hakoniwa-pdu-endpoint` はZenoh有効でビルド・インストール済み(問題なし)
- 実機の `sonar_radar-zenoh-bridge` は設計転回前の古いコミットのままだった(`git pull`で解消)
- ブリッジ機(Pi 5)には `sonar_radar-zenoh-bridge` が一度もクローンされていない、`config/raspi5` もまだ存在しない(想定通り、未着手)
- 実機からMacのzenohd(`192.168.1.195:7447`)へのTCP疎通は問題なし

**対応した変更**

- `run_calibration_smoke_test.py` に `--origin`/`--participants`/`--leader`/`--config` を追加し、同じスクリプトを異なるマシン・役割で使えるようにした(引数省略時は従来の単体検証のまま)
- `bridge/env.sh` を `uname -s` で分岐させ、macOS(`.dylib`/`DYLD_LIBRARY_PATH`)とLinux(`.so`/`LD_LIBRARY_PATH`)の両方に対応させた

**結果**

実機(origin=2, leader)とMac(origin=1, follower)を `calibration_participants={1,2}` でほぼ同時に起動したところ、双方が相手の `calibrated` を実ネットワーク越しに受信し、guardが揃って通過、ほぼ同時に `WAIT_FOR_START_PRESS` に到達した(実機 17:53:31.229 / Mac 17:53:31.279)。`watch_state.py` でも両machineの状態遷移をリアルタイムに観測できた。

**教訓**: 「1台でとりあえず動く」ことと「複数ノードで協調できる」ことの間には、設計上いちばん重要な部分(このプロジェクトの存在理由そのもの)が隠れていることがある。単体検証で満足せず、早い段階で小さいスコープのまま実環境の複数ノードに広げて検証したことで、今回はその部分を安く・早く実証できた。

**追加確認: 実機がfollowerの場合(動作シナリオの別ケース)**

役割を入れ替え、実機(origin=2, follower)とMac(origin=1, leader)で同じ検証を行ったところ、同様に実ネットワーク越しで両者が `WAIT_FOR_START_PRESS` に到達した(実機 18:01:37.652 / Mac 18:01:39.318 で `WAIT_CALIBRATED`、18:01:39.370 / 18:01:39.401 で到達)。現状の実装ではキャリブレーションが `is_leader` を参照しない対称設計であるため、想定通り役割に依存せず成立することも確認できた。

### 得られた教訓(追加)

4. **人間が実機を手作業で確認するときの「見落とし」も、テストで拾える不具合の一種として扱う。**
   ユーザー自身が実機のコンソールを直接操作しながら2台構成を試したところ、操作に気を取られている間に `WAIT_CALIBRATED` の5秒タイムアウトに気づかず素通りしてしまった。原因はコードの不具合ではなく(`is_leader`はこの範囲では未使用で、収束ロジック自体は正しく動いていた)、「人間が気づけるかどうか」という別の観点の不足だった。対処として `console_report.py` を新設し、失敗系の状態(`CALIBRATION_FAILED`/`SCAN_FAILED`)を赤字+反転表示の明滅で強調するようにした。当初はターミナルベル(`\a`)だけで対応したが、SSH接続元の端末アプリの設定や実機側のスピーカー有無に依存して鳴らないことがあると判明したため、ANSIエスケープによる反転表示の明滅(0.15秒間隔×4回)を主手段に変更した。これも `sonar_radar_app.py` には依存を持ち込まず、`state_reporter.py` と同じ横断的関心事として切り出している。

### 実験: IPアドレスの代わりにmDNS(.local)名を使う

「別のルーターのネットワークに繋ぎ変え、各machineに現在と異なるIPが振られたら、どのファイル・設定を更新する必要があるか」という問いから、実際にIPに依存している箇所を洗い出したところ、`config/raspi4b/comm/zenoh/client.json5` の接続先(Macのzenohdへの`tcp/<IP>:7447`)だけがネットワーク変更の影響を受けることがわかった。

そこで、IPの代わりにMacのmDNSホスト名(`Shin-MacBookAir-15.local`、`scutil --get LocalHostName`で確認)を使えないか試した。実機からのDNS解決・TCP接続の生ソケットレベルでの確認に続き、`config/raspi4b/comm/zenoh/client.json5` の接続先を実際にmDNS名へ書き換えて2台構成のキャリブレーション検証を再実行したところ、Zenoh自体を含めて問題なく動作した(実機 19:50:51.616 / Mac 19:50:53.195 で `WAIT_CALIBRATED`、19:50:53.248/53.272 で到達)。

**留保**: これは今使っているルーターでmDNS(マルチキャスト)が通ることを確認したに過ぎない。別のルーターのネットワークでも同様に通るとは限らない(AP isolationやマルチキャストフィルタ設定次第)。うまく通れば、ネットワークが変わるたびのIP書き換えという手間そのものが不要になるが、通らない環境では結局IPに戻す必要がある。実際に用意する別ルーターでの検証は次回に持ち越し。

### 実験: 別ルーター(上流インターネット無し)での検証、mDNSは不採用に

実際にデモ会場を想定した別ルーター(`192.168.11.0/24`、上流インターネット無し)を用意し、検証した。

**構成**: Mac は Wi-Fi(自宅ネットワーク、このセッション自体の維持用) と 有線(新ルーター、`192.168.11.2`)の両方に同時接続(マルチホーム)。実機は有線を新ルーター(`192.168.11.3`)へ接続。この構成であれば、実験用ルーターに上流インターネットが無くても、このセッション自体は途切れずに作業できることを確認した(Mac側がインターネットを失わない限り、セッションは維持される)。

**mDNS方式は不採用と判断**: 前回の実験結果を踏まえ、まずmDNS名(`Shin-MacBookAir-15.local`)で接続を試みたところ、この新ルーター環境では失敗した。原因は、Macが複数のネットワークインターフェース(Wi-Fi、既存有線、新ルーター用有線)を同時に持つ(マルチホーム)ため、mDNS解決が無関係なインターフェースの、既に使われていないリンクローカルアドレス(`169.254.x.x`)を返してしまうこと。前回の「留保」で懸念していた通りの結果になった。**マルチホームな開発機を使う限り、mDNS名による接続先解決は信頼できない**という結論に至り、IP直書きの運用に戻した(`config/raspi4b/comm/zenoh/client.json5` のコメントに、既知の自宅IP・デモ会場IPの両方を残してある)。

**結果**: `config/raspi4b/comm/zenoh/client.json5` の接続先をIP(`192.168.11.2`)に書き換えた上で、実機・Macの2台構成キャリブレーション検証を新ルーター経由で再実行したところ、問題なく成立した(実機 12:31:15.103 / Mac 12:31:16.603 で `WAIT_CALIBRATED`、12:31:16.654/16.682 で到達)。**システムの中核機能はネットワークを変えても、IPの書き換えだけで問題なく移行できる**ことが確認できた。

**運用メモ**: 当初は `client.json5` を直接編集してIPを書き換えていたが、「編集は事故りやすい」との指摘を受け、`client.home.json5`(自宅用)・`client.demo.json5`(デモ会場用)をあらかじめ両方用意しておき、使う方を `client.json5` にコピーする運用に変更した(`cp client.demo.json5 client.json5` のように)。この方式だと、ディレクトリのファイル一覧を見ただけで「ネットワーク切り替えが必要な設定がある」こと自体に気づける、という副次的な利点もある。現在は `client.demo.json5` の内容が `client.json5` に反映されている(デモ会場設定が有効)。

## マイルストーン2: WAIT_FOR_START_PRESS 〜 SCANNING到達 (完了)

### 実装したもの

`sonar_radar_app.py` に `WAIT_FOR_START_PRESS` / `WAIT_FOR_START_RELEASE` / `WAIT_FOR_SCAN_START` / `SCANNING`(到達まで)を追加。`bridge/run_start_smoke_test.py` を新設。

実ハードウェア(`starter`/`marker_detector`/`radar_base`/`scanner`)はまだこの層に接続されていないため、`SonarRadarApp` のコンストラクタで関数を注入できるようにした(未指定時はfalse/no-op/0を返す安全なスタブ)。テストでは `starter_is_pushed` をタイマー駆動の擬似スイッチ(`_FakeStarter`、一定時間後に押下、さらに一定時間後に解放を模擬)で代替した。

### 確認した内容

- 単体(自己ループバック): leader役で `WAIT_FOR_START_PRESS`(擬似押下)→`WAIT_FOR_START_RELEASE`(擬似解放)→`WAIT_FOR_SCAN_START`(start publish)→(自己受信)→`SCANNING` まで到達
- 実機(follower)+Mac(leader)、新ルーター(`192.168.11.0/24`)経由の2台構成: 双方が `WAIT_CALIBRATED`→`WAIT_FOR_START_PRESS` まで揃った後、Macがローカルで擬似押下→解放→`start`をpublish、実機は受信して直接`SCANNING`へジャンプ、Macも自分の`start`を自己受信して`SCANNING`へ到達。leader/followerの非対称設計(押下→解放→publishという手順を踏むのはleaderのみ、followerは受信するだけで目的の状態へ直接進む)が実際のネットワーク越しに機能することを確認できた。

### 実機のstarter(force sensor)実接続、教訓: ハードウェア準備完了を問い合わせる方法が無い

ユーザーから、擬似スイッチではなく実機を実際に操作して試したいという要望を受け、`bridge/real_starter.py`(`RealStarter`)を新設した。`sonar_radar/raspi/libspikehat`のPythonバインディングを直接使う(`sonar_radar`本体はimportしない設計方針の中で、ハードウェア抽象化ライブラリであるlibspikehatだけは例外的に直接使う)。

**つまずいた点と教訓**:

1. **BuildHATのファームウェアロードを忘れていた。** `sonar_radar/raspi/run.sh`が`python3 -c "from buildhat import Motor; Motor('A')"`を別プロセスで実行してからアプリ本体を起動している手順を見落としており、`force_is_pressed()`が「フォースデータなし」のRuntimeErrorを送出していた。同じ手順を`real_starter.py`に追加して解消した(ただし、計測すると連続2回の呼び出しはいずれも約0.78秒で、"ロード"というより毎回の軽い確認処理のようだった)。

2. **ハードウェア初期化にかかる時間は、電源投入直後やハードウェアリセット直後は長い(ユーザーの経験では10秒近く)。** これがキャリブレーションのタイムアウト(既定5秒)より長くなりうるため、`CALIBRATION_FAILED`に落ちた。`calibration_timeout_sec`をコンストラクタで指定可能にしたが、これは対症療法にはならない: **その5秒は「準備が整いrun()が動き出してから、相手のcalibratedが揃うのを待つ時間」であり、ハードウェア初期化にかかる時間を吸収するためのものではない**、という指摘を受けた。ハードウェア初期化は`broker.open()`より前、`run()`が動き出す前に完了させる設計のままとした。

3. **根本的な制約: `libspikehat`(および土台のbuildhatライブラリ)には、ソフトウェアから「準備完了か」を問い合わせるAPIが無い。** 実際に読んでみて、データがまだ届いていなければ例外が返る、という形でしか判断できない。したがって、ハードウェア初期化にどれだけ時間がかかるかをアプリケーション側から正確に・事前に把握する方法が無い。`RealStarter.is_pushed()`は、この「データ未着」を例外で検知して「未押下」として扱う(fail-safeにする)ことはできるが、これは根本的な解決ではない。**実務上は、実機側を先に起動して目視で動作開始(broker.open()以降のログ)を確認してから相手側を起動する、という運用でしか確実に担保できない。** コード側のタイムアウト調整では本質的には解決しない、という理解で合意した。

   公式ドキュメント([Getting started with the Raspberry Pi Build HAT](https://www.raspberrypi.com/documentation/accessories/build-hat.html), [PDFガイド](https://pip.raspberrypi.com/documents/RP-008141-DS-getting-started-build-hat.pdf))で以下2点を確認した。
   - ファームウェアロードは **Raspberry Pi起動ごとに1回だけ** で、以降のPython実行では待たされない("Subsequent executions of a Python program will not require this pause.")。実測(0.78秒×2回連続)と整合する。
   - **LED(赤→消灯、緑点灯)による物理的な準備完了サインがある。** ソフトウェアAPIでの問い合わせはできないが、目視確認の手段としては存在する。

   この裏付けにより、**「電源投入直後は10秒近く待った」という経験は、ファームウェアロードそのものではなかった**ことが分かった(再ロードは高速なため)。実際に計測すると、`RealStarter()`の構築(ファームウェアロード＋force sensorが有効なデータを返すまでの待ち)に**約6.35秒**かかっており、ファームウェアロード(約0.78秒)とは別に、フォースセンサー自体が有効なデータを返し始めるまでに数秒かかることが分かった。

4. **「人がLEDを見てから相手を起動する」を自動テストの前提にする必要は無い。** `RealStarter`は既に「データ未着なら例外」という形でハード側の準備状況を検知できていたため、コンストラクタ内で`force_is_pressed()`が例外を出さずに読めるようになるまでポーリングして待つ`_wait_until_ready()`を追加した。これはLED目視の代替となる、ソフトウェアだけで完結する準備完了確認であり、自動テストでも人手なしで安全に待てる。準備ができなければ明示的に例外を送出する(既定タイムアウト15秒)。

5. **残り約5.5秒の内訳は、SPIKEセンサー全般に共通する「安定待ち」らしい。**(※後日の全ポート実測により訂正。下記「実機での初期化・キャリブレーション所要時間の実測」を参照) ユーザーの経験(SPIKEアプリケーション開発での不文律)によれば、カラーセンサーはライトが安定するまで、距離センサーは音の反射を確認できるまで、初期化後にそれぞれ安定待ちの時間が必要とのこと。フォースセンサーに限らず、今後 `marker_detector`(カラー/距離センサー)や `scanner`(距離センサー)を実接続する際にも、同様のポーリング待ち(`_wait_until_ready`と同じパターン)が必要になる見込み。

**結果**: `--calibration-timeout`を60秒に緩め(実機起動側とMac側の起動タイミングを厳密に揃えなくても済むように)、実機(leader, `--real-starter`)とMac(follower)を新ルーター経由の2台構成で実行したところ、キャリブレーションが揃った後 `WAIT_FOR_START_PRESS` で待機し、ユーザーが実機のフォースセンサーを実際に押して離すと、実機は `WAIT_FOR_START_RELEASE` → `WAIT_FOR_SCAN_START` → `SCANNING`、Macは `start` を受信して直接 `SCANNING` へ到達した(16:04:45.032 `WAIT_FOR_START_PRESS` → 16:04:46.669 `WAIT_FOR_START_RELEASE` → 16:04:46.734/46.773 `SCANNING`、押下から到達まで約1.7秒)。**擬似スイッチではなく実機の物理ボタンを使った、初めてのエンドツーエンド動作確認。**

## 設計修正: CALIBRATING状態の追加(キャリブレーション処理自体が未実装だった欠落を修正)

マイルストーン2までの実装では、`WAIT_CALIBRATED`が`radar/dome/calibrate`をpublishして`calibrated`の到達を待つだけで、**実機にもシミュレータにも「受信したcalibrateに応じて実際にキャリブレーションを実行する」処理自体が存在しなかった**(スモークテスト側の`consume_calibrate_received()`→即`publish_calibrated()`という最小スタブで代替していた)。ユーザー自身がこの欠落に気づき、指摘を受けて設計を修正した。

**修正後の設計**: `WAIT_CALIBRATED`を3状態に分割し、`WAIT_CALIBRATED`という名前自体も他の`WAIT_FOR_X`命名規約に合わせて廃止した。

- `WAIT_FOR_CALIBRATE`: entryで`calibrate`をpublish、`timer_start(5s)`。`calibrate`を受信したら`CALIBRATING`へ。
- `CALIBRATING`: entryで`radar_base_calibrate()`を実行(モーターホーミング等、完了に時間がかかる非同期処理を想定)。`radar_base_is_calibrated()`の完了を待って`WAIT_FOR_CALIBRATED`へ。
- `WAIT_FOR_CALIBRATED`(旧`WAIT_CALIBRATED`を縮小): entryで`calibrated`をpublish、参加者全員の`calibrated`到達(`check_calibration_participants()`)を待って`WAIT_FOR_START_PRESS`へ。exitで`timer_stop()`。

`radar_base`クラスに`calibrate()`/`is_calibrated()`操作を新設(中身は空、実接続は次のマイルストーンで着手)。`sonar_radar_app.py`側にも同名の注入可能スタブを追加し、`run_calibration_smoke_test.py`/`run_start_smoke_test.py`にあった旧スタブループは不要になり削除した。

### 得られた教訓

6. **UMLの完了遷移(イベント無し自動遷移)のガード条件は、1度しか評価されない。** 当初`CALIBRATING`→`WAIT_FOR_CALIBRATED`を「ガード`[radar_base_is_calibrated()]`付きの自動遷移」として設計したが、ユーザーから「完了遷移のガードは1回評価されて偽だとその後評価されなくなる、毎tickポーリングしたいなら`starter_is_pushed()`と同じようにガードではなくイベントとして書くべき」との指摘を受けた。この図では「レベルトリガーの条件をイベント欄に書く(エッジトリガではなく評価時状態による判定として扱う)」という規約が既に`starter_is_pushed()`等で使われており、それに合わせてイベント欄に`radar_base_is_calibrated()`と書き、ガードは空にした。

7. **タイマー停止の多重呼び出しは、実装が冪等なら設計上問題にならない。** `WAIT_FOR_CALIBRATED`の失敗経路(`timer_is_fired()`→`CALIBRATION_FAILED`)では、exit(`WAIT_FOR_CALIBRATED`側)とentry(`CALIBRATION_FAILED`側)の両方で`timer_stop()`が呼ばれる形になった。`spikehat_timer_reset()`の実装(`_deadline=None, _fired=False`を設定するだけ)を確認し、冪等であることを確認した上で「現状維持でよい」と判断した。また、この後始末を「宛先側のentryに一本化する」ため`WAIT_FOR_START_PRESS`側に`timer_stop()`を足す案も検討したが、「`WAIT_FOR_START_PRESS`はキャリブレーションとは別の関心事であり、そこにキャリブレーションのタイムアウト処理の後始末を書くのは責務の侵犯になる」との判断で見送った。責務の分離を、コードの重複排除よりも優先した判断。

## 実機での初期化・キャリブレーション所要時間の実測(教訓5の訂正)

CALIBRATING導入にあたり、実機のハードウェア初期化・キャリブレーションが実際どれくらいの時間で完了するのか(そして、その間ずっと同期的にブロックしてよいのか)を、実機(`192.168.11.3`)で直接計測して確認した。

**port_config()単体の計測(4ポート全て)**: `hat.port_config(PORT_MOTOR/FORCE/COLOR/DISTANCE, ...)` を全ポート分計測したところ、支配的なのは `SpikeHat()` のコンストラクタ自体(約5.3秒、複数回の実測で5.31〜5.31秒台と非常に安定)であり、**`port_config()` 自体は4ポートとも実質0秒、各センサーの初回読み取り(force/color/distance/motor)も1〜2回のポーリングでほぼ即座に成功した**。前回のマイルストーン2「教訓5」で「カラー/距離センサーも安定待ちが必要」と推測していたが、**今回の全ポート計測ではその推測は裏付けられなかった**。以前 `RealStarter()` 構築で見えた約5.5秒の残り時間は、フォースセンサー固有の安定待ちではなく、`SpikeHat()` 構築(ハードウェアハンドシェイクと思われる)そのものだった可能性が高い。

**カラーセンサーのランプが点灯しない件**: 実機を目視していたユーザーから、`color_read_hsv()` は値を返すのにカラーセンサーのランプが点灯していないという指摘を受けた。`libspikehat`(`/home/kuboaki/Projects/libspikehat/src/sensor.c`)の `color_switch_mode()` を確認したところ、モード切替コマンドは `"port %d; port_plimit 1; set -1; select; select %d; selrate 10"` で、コメントには「`set -1` でランプ電源を**維持**してからモード切り替え」とある。「維持」ということは能動的にONにする命令ではなく、消灯状態ならそのまま消灯し続ける可能性がある。**値の読み取りが成功することと、ランプが物理的に点灯することは別の話であり、libspikehat側の実装課題として残っている**(このセッションでは未修正、原因の特定まで)。

**`sonar_radar.py` 実機実行での経過時間ログ追加**: 単体実行では完了を待てばよかったが、Zenoh版では待機中に他ノードとの協調(calibrateの送受信等)が並行して起きるため、「何にどれだけ時間がかかっているか」を見えるようにする必要があるという指摘を受け、一時的な計測ではなく `sonar_radar.py` 本体に恒久的なタイムスタンプ出力を追加した(`SonarRadarSM` の各状態遷移ログに `self._clock()`、`main()` に `SpikeHat()` 構築時間の直接計測を追加)。コミット `74f374b`(直前の `038ed15` 差し戻し `19eccc5` の上に積む形)。

実機で `time python3 sonar_radar.py` を複数回実行し、以下の傾向を確認した。

| 区間 | 実測値(複数回) | 傾向 |
|---|---|---|
| `SpikeHat()`構築 | 5.31秒(直接計測)、5.31秒、5.314秒(独立計測) | **非常に安定した固定コスト** |
| キャリブレーション(`CALIB_TO_ZERO`+`CALIB_TO_OFFSET`) | 2.21秒、2.56秒、2.67秒 | 概ね2.2〜2.7秒の範囲で安定 |
| ボタン押下待ち(`WAIT_FOR_START`) | <1秒、3.77秒、1.20秒 | **人間の反応時間依存で大きくばらつく** |
| 0位置復帰(`RETURN_TO_ORIGIN`) | 約2.2秒(推定)、3.81秒、5.07秒 | スキャンで回転した角度に比例して変動 |

**設計への示唆**: `SpikeHat()`構築と固定`sleep(1.0)`(合計約6.3秒)は、通信も何も始まっていない段階の純粋な同期ブロックであり問題ない。一方、**モーターホーミング自体(約2.2〜2.7秒)を、Zenoh版の`CALIBRATING`状態で`radar_base_is_calibrated()`を毎tickポーリングする設計(同期ブロックにしない)にしたのは正しい判断だった**ことが、この実測で裏付けられた。もし同期ブロックにしていたら、その間、相手ノードからのZenohメッセージ処理が止まってしまうところだった。

## Zenoh版を実機で動かす: キャリブレーション(radar_base)の実接続(完了)

`bridge/sonar_radar_app.py` の `radar_base_calibrate`/`radar_base_is_calibrated` はこれまでスタブ(`lambda: True` 等)のままだった。`bridge/real_starter.py`(`RealStarter`)と同じ設計方針(`sonar_radar-zenoh-bridge` は `sonar_radar` 本体をimportせず、ハードウェア抽象化ライブラリの `libspikehat` だけを直接使う)を踏襲し、`bridge/real_radar_base.py`(`RealRadarBase`)を新設した。

**実装**: `sonar_radar.py` の `CALIB_TO_ZERO`/`CALIB_TO_OFFSET`(毎tick `motor_pwm()` で微調整する実装)とは異なり、`spikehat` の `motor_run_to_position()`(非同期・fire-and-forgetでBuildHAT側がランプ移動を行う)を使う設計にした。`calibrate()`を1回呼ぶと機械的0位置への移動コマンドを送り、以後`is_calibrated()`を毎tickポーリングするだけで、内部で「0位置到達→オフセット位置への移動コマンド発行→オフセット到達」の2段階を自動的に進める。`CALIBRATING`状態の「entryで1回・以後毎tickポーリング」という構造にちょうど合う。`run_calibration_smoke_test.py`に`--real-radar-base`フラグを追加した。

**結果**: 実機(`192.168.11.3`、origin=2)で `--real-radar-base` を指定して実行したところ、`WAIT_FOR_CALIBRATE` → `CALIBRATING`(実際にモーターが機械的0位置→オフセット位置へホーミング) → `WAIT_FOR_CALIBRATED` → `WAIT_FOR_START_PRESS` まで到達した。ユーザー自身が実機のターミナルで直接実行して確認(pushしなくても、`scp`で転送済みのファイルだけで実機での動作確認ができることも確認できた)。**Zenoh版のCALIBRATING状態が、実際にモーターホーミングを行う実機で初めて成功したエンドツーエンド確認。**

### 次のマイルストーン(継続)

`MARKER_DETECTED` 以降(`detected`の対称処理、`WAIT_FOR_INVERT`、stopの対称処理、`SCAN_FAILED`)。同じ進め方(1状態ずつ実装→実際のZenohで確認)を継続する。実機のstarter実接続での2台構成テストも、この記録を踏まえて再挑戦する(実機側を先に起動する運用で)。
