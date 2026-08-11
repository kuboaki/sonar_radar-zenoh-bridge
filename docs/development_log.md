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

## マイルストーン3: マシン間キャリブレーション協調の廃止(設計の再転回、完了)

### 背景: 起動順序ルールが何度直しても再発した

動作シナリオ1(実機単体)・動作シナリオ2(シム単体)・実機+Macの2台構成それぞれで実地検証を重ねる中で、「双方のbroker.open()(Zenoh購読)が、お互いの`calibrated`publishより先に完了している必要がある」という制約に起因する取りこぼしが、起動順序ルールを2回訂正しても解消しなかった。

1. 最初のルール「Mac(follower)の`hako-cmd start`より先に実機を起動する」は、実機がleaderの回ではたまたま成立していたが、Macをleaderにした回で失敗した。Macの`hako-cmd start`が先に走り、起動が遅い実機の購読が間に合わず`CALIBRATION_FAILED`になった。
2. 「leader/followerに関係なく、常に実機を先に起動し、Macの`hako-cmd start`を最後にする」に訂正したが、これも失敗した。実機側のキャリブレーション自体が数秒で完了してしまうため、人がチャット上の合図を読んで`hako-cmd start`を打鍵する時間より速く`calibrated`がpublishされ、まだ購読を開いていないMac側が結局取りこぼした。

**根本原因**: どちらのルールも、「購読開始が人の操作待ちでゲートされている側(Macの`hako-cmd start`)は、相手の完了に間に合わない可能性がある」という構造そのものを解決していなかった。起動順序をどう入れ替えても、相手側の処理が人間の反応時間より速く終われば同じ問題が起きる。

### 設計判断: 協調を無くす

この構造的な問題を受けて、「起動順序を工夫する」ではなく「マシン間のキャリブレーション協調そのものを無くす」方向へ転回した。各マシン(実機・シム)は、人が起動してからキャリブレーションが終わるまでを、他マシンとの通信なしに独立して完結させる。

- `INIT`(`broker.open()` → `hardware_initialize()`)から`CALIBRATING`(ローカルなハードウェアキャリブレーションのみ)までを1つの流れに閉じ込め、完了したら自動的に`WAIT_FOR_START_PRESS`へ遷移する
- `WAIT_FOR_CALIBRATE`/`WAIT_FOR_CALIBRATED`の2状態、`calibrate`/`calibrated`のPDUメッセージ、`check_calibration_participants()`ガードを全廃
- `CALIBRATION_FAILED`は残すが、用途を「マシン間協調の失敗」から「ローカルなハードウェア障害(物理的にモーターが固着している等)」に変更し、タイムアウトを20秒にした
- `timer_stop()`は、教訓7で「`WAIT_FOR_CALIBRATED`のexitと`CALIBRATION_FAILED`のentryの両方で呼ばれるが冪等だから問題ない」としていたが、今回`CALIBRATING`という単一の状態に統合されたのを機に、「本来`CALIBRATING`でなくなったら止めるものである」という意味論に立ち返り、`CALIBRATING`のexitだけに一本化した

### 進め方: 図→クラス図→コードの順で追従

いつも通り、まずAstahの状態機械図を直す(`WAIT_FOR_CALIBRATE`/`WAIT_FOR_CALIBRATED`削除、`INIT→CALIBRATING`、entry/exitの`timer_stop()`整理、作業用に貼っていた参照テーブルの削除)。次に、状態機械図の変更で発生したクラス図側の不整合(`sonar_radar`の`check_calibration_participants()`、`broker`の`publish_calibrate`/`publish_calibrated`/`is_calibrated_received_from`)を、忘れないうちにその場で整理した。両方の図に残っていた、廃止した設計を前提とする古いノート(5件)も削除した。

その後、コードを図に追従させた: `sonar_radar_app.py`(state enum・tick関数・`_transition_to`)、`broker.py`(publish/consume/購読)、`app_runner.py`/`run_real.py`/`run_hako.py`(不要になった`--participants`引数の除去)、`pdu/pdutypes.json`・`config/{mac,raspi4b}/comm/zenoh_pubsub_comm.json`・`watch_all.py`(calibrate/calibratedチャンネルの除去)。`demo_*.bash`の起動順序に関する説明も、協調廃止により順序が自由になった旨に書き換えた。

### 確認した内容

- 1プロセス自己ループバック(スタブハードウェア): `INIT → CALIBRATING → WAIT_FOR_START_PRESS → WAIT_FOR_START_RELEASE → WAIT_FOR_SCAN_START → SCANNING → TERMINATED` を確認(PDUチャンネル欠番によるエラー無し)
- 実機単体(動作シナリオ1、`--real-starter --real-radar-base`): Build HATファームウェアロード → `CALIBRATING`(実際にモーターホーミング) → `WAIT_FOR_START_PRESS` → … → `SCANNING` → `TERMINATED` まで、`CALIBRATION_FAILED`に陥らず到達
- 実機(leader)+Mac(follower、MuJoCoシム経由の`run_hako.py`)の2台構成: 起動順序を意識せず両者を起動し、`hako-cmd start`後に実機のstarterボタンを押すだけで、両machineとも`SCANNING`まで到達

### 得られた教訓

8. **「起動順序のルールで解決する」は、根本原因が構造的な非対称性にある場合は対症療法にしかならない。** 同じ種類の取りこぼしが起動順序ルールを2回訂正しても再発したことが、「人の操作待ちでゲートされる側は原理的に間に合わない可能性がある」という構造上の問題に気づく決め手になった。表面的な手順の調整を繰り返す前に、「そもそも待ち合わせという設計自体が必要か」を疑うべきだった。

9. **状態機械が新設計に変わったら、それを前提にしていた過去の設計判断(教訓7)も見直す。** 「`timer_stop()`の多重呼び出しは冪等だから問題ない」という教訓7の判断は、当時の`WAIT_FOR_CALIBRATED`/`CALIBRATION_FAILED`という2状態構成では正しかったが、`CALIBRATING`1状態に統合された今、「なぜ2箇所で呼んでいるのか」を問い直すと、`timer_stop()`本来の意味論(そのタイマーを使う状態でなくなったら止める)には`CALIBRATING`のexitでの1箇所だけで十分だと分かった。「冪等だから問題ない」という判断は「今のままで害はない」の確認であって、「これが正しい設計である」の確認ではないことに注意が要る。

10. **図・クラス図・ドキュメント・コードの追従順序を守ることで、修正漏れが起きにくくなる。** 状態機械図→(気づいた時点で即座に)クラス図→設計ドキュメント→コード→README/development_logという順で進めたことで、「クラス図の`check_calibration_participants()`を消し忘れる」「READMEの起動順序節だけ古いまま残る」といった典型的な取りこぼしを避けられた。特にクラス図は「今やらないと忘れる」という自己申告のタイミングでその場処理したのが効いた。

## ハードウェア抽象層の統一: RadarHardware(RealHardware/HakoHardware)導入(完了)

### 背景

`sonar_radar`本体は`libspikehat`/`libspikehat_sim`という「同一ヘッダ(`libspikehat.h`)に対する実機/シムの2実装」パターンでハードウェアアクセスを抽象化しているが、`sonar_radar-zenoh-bridge`側の呼び出しスクリプト(`run_real.py`/`run_hako.py`)はこのパターンを採用しておらず、`run_real.py`は`hw`辞書による遅延束縛、`run_hako.py`は`on_manual_timing_control`内での都度構築、と個別の配線になっていた。次のマイルストーン(`MARKER_DETECTED`以降)に進む前の整理として、この非対称を解消した。

### 設計判断

`bridge/hardware.py`に`RadarHardware(abc.ABC)`を新設し、`initialize`/`radar_base_calibrate`/`radar_base_is_calibrated`/`starter_is_pushed`/`close`の契約を定義。`RealHardware`(Build HAT経由)と`HakoHardware`(`HakoSpikeHat`経由)で実装した。

- `RealHardware`は`initialize()`内で`real_hat.create_real_hat()`を1回だけ呼び、`RealRadarBase`/`RealStarter`が同じシリアル接続(`hat`)を共有する必要がある(複数の同時オープンをサポートしない)という既存の制約をそのままカプセル化した。`radar_base`/`starter`未使用時は既定スタブ(`is_calibrated()`は即`True`、`is_pushed()`は常に`False`)を返す。
- `HakoHardware`は、`hako_hat`(`HakoSpikeHat`)自体は`hakopy`のasset登録の都合で呼び出し側(`run_hako.py`)が`initialize()`より前に構築して渡す(この構築だけは`SonarRadarApp`のINITタイミングに合わせられない、`hakopy`フレームワーク側の制約)。`HakoRadarBase`/`HakoStarter`の構築は軽量・即時なので実機のような遅延の必要は無いが、対称性のため`initialize()`内で行う。
- `SonarRadarApp`のコンストラクタは今まで通り4つの独立したコールバックのままで変更なし。状態機械図が個別のガード/エフェクト関数として設計しているため、これを1個の`hardware`オブジェクトにまとめるのは図の設計意図から外れると判断し、統一対象は`run_real.py`/`run_hako.py`側の配線だけに絞った。状態機械図・クラス図とも、この階層の実装詳細はもともと対象外のため変更なし。

`run_real.py`の`_FakeStarter`(leaderの擬似ボタン)はテスト専用の関心事として、`RadarHardware`側には移さず引き続き`run_real.py`側に残した。

### 確認した内容

1プロセス自己ループバック(スタブハードウェア)と実機単体(動作シナリオ1、`demo_real_leader.bash`)で、Build HATファームウェアロード→`CALIBRATING`(実際にモーターホーミング)→`WAIT_FOR_START_PRESS`→`WAIT_FOR_START_RELEASE`→`WAIT_FOR_SCAN_START`→`SCANNING`まで到達することを確認済み。

## マイルストーン4: MARKER_DETECTED以降(detected/stopの対称処理、WAIT_FOR_INVERT、SCAN_FAILED)実装(完了)

### 背景

Astahの状態機械図(`sonar_radar::runのステートマシン図`)は、`MARKER_DETECTED`/`WAIT_FOR_INVERT`/`WAIT_FOR_STOP_PRESS`/`WAIT_FOR_STOP_RELEASE`/`SCAN_FAILED`まで含めて既に設計済みだった(図の変更は不要で、実装のみが追いついていない状態)。Astah MCP経由でプロジェクトファイルから全22遷移を読み取り、ノート(未確定事項の注記含む)も合わせて正確に取得した上で、`bridge/sonar_radar_app.py`に1:1で実装した。

### 実装したもの

start/`WAIT_FOR_SCAN_START`で確立済みの「leaderはローカル検知→publishのみ、実アクションは自分のpublishのループバック受信で行う、followerは受信のみで直接遷移する」パターンを、detected/stopにもそのまま適用した。

- `SCANNING` --[`marker_detector_is_detected()`][`is_leader==true`]--> `MARKER_DETECTED`(entryで`detected`をpublish、2秒タイムアウト)--[`detected`受信]--> `WAIT_FOR_INVERT`(entryで`radar_base_invert_direction()`、無条件で`SCANNING`へ復帰)。followerは`SCANNING`から`WAIT_FOR_INVERT`へ直接遷移し、`MARKER_DETECTED`を経由しない。
- `SCANNING` --[`starter_is_pushed()`][`is_leader==true`]--> `WAIT_FOR_STOP_PRESS` --[`!starter_is_pushed()`]--> `WAIT_FOR_STOP_RELEASE`(entryで`stop`をpublish、2秒タイムアウト)--[`stop`受信]--> `TERMINATED`。followerは`SCANNING`から`TERMINATED`へ直接遷移する。
- `WAIT_FOR_SCAN_START`/`MARKER_DETECTED`のタイムアウト(`timer_is_fired()`)は、どちらも`SCAN_FAILED`(entryで失敗通知+`stop`をpublish)へ遷移し、`SCAN_FAILED`は無条件で通常の`WAIT_FOR_STOP_RELEASE`に合流する(自分の`stop`のループバック受信を待ってから`TERMINATED`へ至る、`stop`の二重publish自体は`consume_stop_received()`が真偽フラグのため無害)。
- `SCANNING` --[`timer_is_fired()`]--> `SCAN_FAILED`という遷移は図に存在していたが、`SCANNING`にはentry/exitでのタイマー起動処理が無く、この遷移が本当に必要かどうか自体が図のノートで「まだわからない」とされていたため、この時点では実装せず`docs/zenoh_state_machine_design.md`の未確定事項に明記するに留めた(このセッションの後半で解決。次の見出し参照)。

### 確認した内容

実際のZenohを使わず、`broker`をスタブ化した検証スクリプトで以下を確認した(publish時に自分自身への即時ループバックをシミュレートする形)。

- leaderのフルサイクル: `INIT`→…→`SCANNING`→(マーカー検出)→`MARKER_DETECTED`→`WAIT_FOR_INVERT`→`SCANNING`→(stop押下)→`WAIT_FOR_STOP_PRESS`→`WAIT_FOR_STOP_RELEASE`→`TERMINATED`
- followerの直接遷移: `WAIT_FOR_START_PRESS`→`SCANNING`→(detected受信)→`WAIT_FOR_INVERT`→`SCANNING`→(stop受信)→`TERMINATED`(`MARKER_DETECTED`/`WAIT_FOR_STOP_PRESS`を経由しない)
- `MARKER_DETECTED`のタイムアウト→`SCAN_FAILED`→`WAIT_FOR_STOP_RELEASE`→`TERMINATED`

検証スクリプト自体は一時ファイルでコミットしていない。実機・シムでの実地確認(Zenoh経由)はまだ行っていない。

## SCANNINGのタイムアウト(ケーブル巻き込み防止)を追加(完了)

### 背景

上記マイルストーン4で保留にした`SCANNING`--[`timer_is_fired()`]-->`SCAN_FAILED`遷移について、ユーザーから実装方針の説明を受けた。`CALIBRATING`のタイムアウト(20秒)は「実機で機構のずれを外してはめ直す猶予」だが、`SCANNING`のタイムアウトは目的が逆で、「ドームが旋回しすぎてセンサーケーブルを巻き込む前に止める」ための早期カットオフ。`WAIT_FOR_INVERT`→`SCANNING`の再入がマーカー間の1レッグに対応するため、基準値は「1レッグの所要時間の実測＋α」で決めることにした。

### 実測

**実機**: `~/Projects/sonar_radar/raspi/sonar_radar.py`をそのまま使い、フォースセンサーの物理押下無しで開始・終了できる使い捨て計測スクリプト`/tmp/measure_scan_period.py`(`SpikeHat.force_is_pressed()`をオーバーライドしてボタン押下を自動注入、`sim/sonar_radar_sim.py`の`--auto-start`/`--auto-stop`と同じ技法を実機に適用したもの)を作成し、実機(`192.168.11.3`)で40秒間の連続スキャンを実行。マーカー検出のタイムスタンプから7レッグ分の所要時間を算出し、4.28〜5.28秒(平均約4.77秒)を得た。計測に使ったスクリプトとログ(`/tmp/measure_scan_period.py`, `/tmp/scan_real_timing.json`, `.log`)はユーザーの指示によりPi上の`/tmp`に残してある。

**スタンドアロンSIM**: 同様の計測をMac上のスタンドアロンSIM(`~/Projects/sonar_radar/sim/sonar_radar_sim.py`)でも行うため、まずREADME(`README_ja.md`「スタンドアロンSIMでの実行(MuJoCo)」)記載の手順通りに環境を検証した。`.venv`が`uv venv --python /opt/homebrew/bin/python3.12`で作成されていること(Python 3.12.13)、`mujoco`パッケージとMuJoCo.appのバージョンが一致(3.10.0)していることを確認し、README記載の非インタラクティブ実行例(`python3 sim/sonar_radar_sim.py --auto-start 3 --auto-stop 20`)がそのまま動くことも確認した上で、`--auto-start 2 --auto-stop 45`で40秒超のスキャンを実行。8レッグ分の所要時間は4.95〜4.97秒と非常に安定していた。実機とシムのログ(`/tmp/scan_sim_timing.json`, `.log`, `/tmp/scan_sim_readme_check.json`, `.log`)もユーザーの指示によりMac上の`/tmp`に残してある。

実機とシムの値は近く(最大約5.3秒)、`mujoco_model/studio_to_mujoco.md`に明記された「`--speed`のデフォルトは実時間固定。実機とsimの動作時間を直接比較できることが本プロジェクトの前提」(`[[feedback_sonar_radar_realtime_sim]]`参照)という設計意図が実測でも裏付けられた。

### 決定

最大実測値(約5.3秒) + α(1秒、ユーザー指定。実験不足のための暫定値で実機ではやや大きすぎる可能性があるとの認識、今のところの上限の目安) = **6.3秒**を`SonarRadarApp`の新規コンストラクタ引数`scanning_timeout_sec`のデフォルト値とした。

### 実装したもの

- Astah(`docs/sonar_radar_zenoh_bridge.asta`): `SCANNING`にentry `timer_start(6.3s)`/exit `timer_stop()`を追加。`SCANNING`--[`timer_is_fired()`]-->`SCAN_FAILED`遷移に付いていた「まだわからない」ノートを、上記の決定内容(目的の違い・基準値の根拠)に更新した。
- `bridge/sonar_radar_app.py`: `scanning_timeout_sec: float = 6.3`をコンストラクタに追加。`SCANNING`のentry(`_transition_to`)で`timer_start(self._scanning_timeout_sec)`、`_tick_scanning`の全ての遷移経路(stop/marker検出/stop受信/detected受信/timer_is_fired)でexitの`timer_stop()`を追加。`WAIT_FOR_INVERT`からの再入時も`_transition_to(State.SCANNING)`経由でタイマーが取り直される。
- `docs/zenoh_state_machine_design.md`: 未確定事項からこの項目を削除し、「SCANNINGのタイムアウト(ケーブル巻き込み防止)」節を新設して実測値・決定内容を記載した。

### 確認した内容

スタブBrokerでの検証スクリプトに以下を追加して確認した(一時ファイルでコミットしていない)。

- `SCANNING`自体のタイムアウト→`SCAN_FAILED`→`WAIT_FOR_STOP_RELEASE`→`TERMINATED`
- `WAIT_FOR_INVERT`→`SCANNING`再入時にタイマーが取り直される(2レッグ目の`_timer._deadline`が1レッグ目より後になる)こと

既存の3シナリオ(leaderフルサイクル/followerの直接遷移/`MARKER_DETECTED`タイムアウト)も、exitの`timer_stop()`追加後に再実行し、引き続き成功することを確認した。

## マイルストーン5: radar_baseの継続旋回・marker_detector実装、ブリッジ経由タイムアウトの見直し(完了)

### きっかけ: 「動かない」

前マイルストーンではSCANNING/MARKER_DETECTED以降の状態機械ロジックのみが実装されており、`radar_base.run()`(継続旋回の開始)がどこからも呼ばれておらず、`invert_direction()`も未実装スタブ(`NotImplementedError`)のままだった。実機での動作確認中、ユーザーから「スターターのボタンを押しましたが。動かないです」との報告を受けて発覚した。

### 実装したもの

- `real_radar_base.py`/`hako_radar_base.py`: `run()`(冪等、既に回転中なら何もしない)/`stop()`/`invert_direction()`(PWM符号反転、停止せず継続。`sonar_radar.py`の`_tick_scanning()`と同じ設計)を実装。
- `real_marker_detector.py`/`hako_marker_detector.py`新設: `sonar_radar.py`の`is_red()`/`is_blue()`しきい値と、立ち上がりエッジ検出(`_on_marker`)を移植。
- `hardware.py`: `RadarHardware`に`radar_base_run`/`radar_base_stop`/`radar_base_invert_direction`/`marker_detector_is_detected`を追加。`marker_detector`はradar_baseと同じ物理ドーム上にあるため、既存の`use_radar_base`(実機)/常時(シム)のフラグに連動させ、新規フラグは追加しなかった。
- Astah図: `SCANNING`のentryに`radar_base_run()`、`TERMINATED`のentryに`radar_base_stop()`を追加(クラス図で`radar_base`の操作名を再確認した上で、`クラス名_メソッド名`規約に沿って命名)。

### 確認した内容

実機単体で、ドームが実際に旋回し、マーカーで5回連続して方向反転するのを目視確認。シム単体(ビューア)でも同様に確認。

### leader/follower交代テストで判明した問題: ブリッジ経由のオーバーヘッド

実機とMac(シム)のleader/followerを入れ替えて2台構成テストを行ったところ、2周目でfollower(実機)が`scanning_timeout_sec`(6.3秒)でタイムアウトし`SCAN_FAILED`に落ちた。一方、leader(Mac)側のログには対応する`SCAN_FAILED`表示が無く、`SCANNING`から直接`TERMINATED`へ落ちていて、一見不可解に見えた。

**診断**: バグではなく、設計通りの停止伝播経路だった。follower(実機)が自身の`scanning_timeout_sec`で`SCAN_FAILED`に落ち、そのentryで`stop`をpublishする。leader(まだ`SCANNING`中)がそれを受信し、`_tick_scanning()`の`consume_stop_received()`分岐で`SCANNING`から直接`TERMINATED`へ遷移する(follower側のstop受信パターンと同じ経路)。ここまでは正しく機能していた。

**根本原因**: `scanning_timeout_sec`の基準値(6.3秒 = 単体計測の最大実測5.3秒 + α1秒)が、ブリッジのtickループ・Zenoh送受信を介さない**単体計測**(`sonar_radar.py`を直接実行する`measure_scan_period.py`/`sonar_radar_sim.py --auto-start`)を基準にしていたこと。**ブリッジ経由の実際の1レッグは、単体計測より+1〜1.5秒程度長くなる**(6〜6.4秒程度観測)ことが今回初めてわかった。6.3秒という基準値ではマージンが無く、ドームの動き自体には詰まりや異常が無い(目視確認済み)正常な周回でも、まれにタイムアウトしてしまっていた。

### 対応1: 実機/シムでタイムアウト値を分離

ケーブル巻き込みリスクは実機だけの物理的制約で、シムには実在するケーブルが無いことに気づき、既定値を実機/シムで分けた。

- `sonar_radar::app::sonar_radar`クラス自体の既定値: **8秒**(安全側、実機に合わせる)
- `bridge/run_real.py`の`--scanning-timeout`既定値: **8秒**
- `bridge/run_hako.py`の`--scanning-timeout`既定値: **12秒**(シムはケーブルが無いので余裕を持たせ、誤検出によるSCAN_FAILEDを避ける)

### 対応2: タイマー値は属性名で図に書く、という設計原則の明確化

この過程で、「CLI引数 > コンストラクタ引数 > クラス属性(既定値) > 状態機械図はその属性名を参照」という一貫した階層にすべき、との指摘を受けた。`calibration_timeout_sec`/`scanning_timeout_sec`はコード側では既に属性化されていたが、状態機械図には`timer_start(20s)`のように即値のまま書かれており、コードと図が食い違っていた。また`WAIT_FOR_SCAN_START`/`MARKER_DETECTED`/`WAIT_FOR_STOP_RELEASE`の3箇所の`timer_start(2.0)`は、コード側でも名前付き属性になっておらず、単なるハードコードされたリテラルだった。

対応:

- クラス図の`sonar_radar`クラスに`calibration_timeout_sec`/`scanning_timeout_sec`/`publish_confirm_timeout_sec`の3属性(型`double`、既定値付き)を追加した。
- 状態機械図の該当entryを、即値ではなく属性名の参照に統一した(`timer_start(20s)` → `timer_start(calibration_timeout_sec)`等)。
- 上記3状態の`timer_start(2.0)`は、いずれも「自分のpublishがループバックしてくるのを待つ」という同じ目的なので、個別の属性に分けず1つの共通属性`publish_confirm_timeout_sec`(既定2秒)にまとめた。

### 得られた教訓

11. **単体計測とブリッジ経由の計測は別物であり、タイムアウト値の基準にする際はどちらで計測したかを明記する必要がある。** 今回、`measure_scan_period.py`/`sonar_radar_sim.py --auto-start`による単体計測(Zenoh・ブリッジのtickループを介さない)を基準に決めた`scanning_timeout_sec`が、実際のブリッジ経由の運用では+1〜1.5秒のオーバーヘッドを見込めておらず、マージン不足だった。単体計測は「純粋な物理的所要時間」を知るには有用だが、実運用のタイムアウト値を決める際は、実際に使う経路(ブリッジ経由)で計測するか、経路のオーバーヘッド分を上乗せする必要がある。

12. **物理的な安全マージンと、シミュレーションでの利便性は、要求が逆になることがある。** `scanning_timeout_sec`の「ケーブル巻き込み防止」という目的は実機だけの物理的制約であり、シムには実在するケーブルが無い。実機は安全側で小さく、シムは誤検出を避けるため大きく、という非対称な既定値が正解だった。1つの属性の「正しい既定値」を機械的に1つに決めようとせず、「その制約が本当に両方の環境に当てはまるか」を先に問うべきだった。

13. **タイムアウト値をコンストラクタ引数として注入可能にしただけでは不十分で、状態機械図の表記もそれに追従させる必要がある。** `calibration_timeout_sec`は早い段階で属性化されていたが、状態機械図のentry表記は最後まで`timer_start(20s)`という即値のままだった。「CLI引数 > コンストラクタ引数 > クラス属性 > 図はその属性名を参照」という階層を、コードだけでなく図にも一貫させることで、値を1箇所(クラス属性の初期値)変えるだけで設計全体の記述が揃う。

### 次のマイルストーン(継続)

- `pdu_ros_bridge::sonar_radar_ros_bridge`(ブリッジ/監視役、Raspberry Pi 5想定)の設計・実装。
- `scanning_timeout_sec`の新しい既定値(実機8秒/シム12秒)も、あくまで今回の限られた実測に基づく暫定値。実機での連続運用・より多くのサンプルを重ねて適切な値に見直す。

## マイルストーン6: pdu_ros_bridgeの設計に着手、is_leader/is_starterの分離(進行中)

### Raspberry Pi 5の接続とhakoniwa-pdu-ros状況の把握

`pdu_ros_bridge::sonar_radar_ros_bridge`の設計に着手するにあたり、まずRaspberry Pi 5(`192.168.11.4`、ホスト名`ubuntu-desktop`)を実機・Macと同じネットワークへ接続し、状況を確認した。`hakoniwa-core-pro`/`hakoniwa-pdu-endpoint`/`hakoniwa-pdu-ros`は以前のセッション(7/21付のビルドログ多数)で既に導入・ビルド済みだったが、`hakoniwa-pdu-ros`配下に残っていた設定は同梱の汎用サンプル(Drone/pos・cmd、Zenoh接続先も自宅ネットワークの古いIP`192.168.1.92`のまま)のみで、sonar_radar向けの設定は無かった。`sonar_radar-zenoh-bridge`をクローンし、`config/raspi4b/`と同形の`config/raspi5/`(Zenoh接続先はMacの`192.168.11.2`)を新設した。

### 設計方針の議論: 3者(実機・シム・pdu_ros_bridge)の役割分担

ユーザーの要望は「スキャンデータの収集」と「実機・SIMへのstart/stopをROS側から注入」。検討の結果、`consume_start_received()`/`consume_stop_received()`には元々`is_leader`のガードが無いことが分かり(既存コードのまま、leader/followerどちらでも受信で拾える)、**ROSからのstart/stop注入は状態機械側の変更無しに、broker経由でPDUをpublishするだけで実現できる**と判明した。

ただし、この過程で「`is_leader`がマーカー検出の権限とローカルstarterの権限を両方兼ねている」という設計上の結合に気づいた。ユーザーから「start/stopする指示を出すのと、leaderかfollowerかどうかを分けて考える必要がある」「leaderとfollowerは、どちらもレーダーであるという設計を維持する必要がある(実機とSIMだけでも動けるように)」との指摘を受け、以下の役割分担で合意した。

- **starterになれる= start/stopを注入できる**: 実機・シム・broker経由の外部(`pdu_ros_bridge`等)のいずれからも注入可能。
- **start/stopの注入を受け取るのは常に`sonar_radar`クラス(実機かシム)**。`pdu_ros_bridge`自身は`sonar_radar`のインスタンスではないため、受信側にはならない。

### 実装したもの

- クラス図: `sonar_radar`クラスに`is_starter`属性(型`double`ではなく`int`、`is_leader`と同型)を追加。
- 状態機械図: `starter_is_pushed()`のガードを`[is_leader == true]`から`[is_starter == true]`に変更(`WAIT_FOR_START_PRESS`→`WAIT_FOR_START_RELEASE`、`SCANNING`→`WAIT_FOR_STOP_PRESS`の2遷移)。マーカー検出側の`[is_leader == true]`はそのまま。
- `sonar_radar_app.py`: コンストラクタに`is_starter: Optional[bool] = None`を追加(未指定時は`is_leader`と同値、既存呼び出し元との後方互換)。`_tick_wait_for_start_press()`/`_tick_scanning()`の`starter_is_pushed()`ガードを`is_leader`から`is_starter`に変更。
- `app_runner.py`: `run_app()`に`is_starter`引数を追加、`SonarRadarApp`へ貫通。`run_real.py`/`run_hako.py`へのCLIフラグ追加は見送り(既存呼び出しは全て`is_starter`未指定=`is_leader`と同値のまま)。

### 確認した内容

1プロセス自己ループバックで、既存の全経路(`is_starter`未指定→`is_leader`にフォールバック)が壊れていないことを確認済み。

### 次にやること

- `pdu_ros_bridge::sonar_radar_ros_bridge`のクラス図・状態機械図の設計(スキャンデータのROS中継、ROSからのstart/stop注入)。
- `broker.py`にscan購読機能を追加(現状publish専用)。
- `run_real.py`/`run_hako.py`/`demo_*.bash`の非対称パターン(starterだがleaderではない、等)整理は別途(備忘メモ参照)。

### 追記: leader/follower入れ替えテストで、シム12秒/実機8秒の非対称タイムアウトが問題に

`is_starter`分離後、ユーザーが実機・シムで動作確認したところ、シムleader+実機followerの構成で再びタイムアウトが発生した(実機のドームが旋回途中で停止する写真付きで報告を受けた)。

**診断**: `watch_state.py`のログを確認したところ、2周目の`SCANNING`再突入後、実機(follower、タイムアウト8秒)が8.6秒後に`SCAN_FAILED`に落ち、その`stop`をシム(leader、タイムアウト12秒)が受信してSCANNINGから直接TERMINATEDへ落ちていた。シムはまだ12秒の猶予内で正常動作中だった。

**根本原因**: `scanning_timeout_sec`は「leaderとしての物理安全カットオフ」と「followerとして相手のdetectedを待つ通信タイムアウト」の両方を1つのタイマーで兼ねている。followerのタイムアウトがleaderのタイムアウトより短いと、leader側ではまだ正常な周回でも、followerが先に見切りをつけてしまう。leader/followerの役割はデモのたびに入れ替わりうるため、これは実機・シムどちらの役割でも起こりうる。

**対応**: ユーザーの判断で、実機・シムとも既定値を8秒に統一した(`--scanning-timeout`による個別上書きは維持)。`sonar_radar_app.py`(既に8秒)は変更不要、`run_hako.py`の既定値を12秒→8秒に修正。

**保留した本質的な課題**: ユーザーから、「タイムアウトのマージンの差ではなく、実機とシムで互いの旋回位置が同期していないことが本質的な問題」との指摘があった。将来的な改善案として、followerが自分のペースで自走するのではなく、leaderのエンコーダ角度を読んで追従旋回する(位置追従制御に変える)ことで、両者の位置がずれる余地自体を無くせるのではないか、という着想が出た。Zenoh経由の遅延など別の懸念は残るが、leaderがマーカー・タイムアウトで安全に囲われて動いていれば、followerは現状より確実に追従できると見込まれる(暴走・通信途絶時の安全装置として、タイムアウトによる遷移自体は引き続き必要)。今回は対応せず、設計ドキュメントに記録するに留めた。

### 得られた教訓

14. **1つのタイマー/タイムアウト値に複数の異なる目的を持たせると、片方の都合が他方を壊すことがある。** `scanning_timeout_sec`は「物理安全カットオフ(leader視点)」と「相手を待つ通信タイムアウト(follower視点)」を兼ねていたため、leader/follower双方に別々に最適な値を与えると、follower役の側が短すぎてleader役の側の正常な遅延を殺してしまうという組み合わせ問題が発生した。役割によって性質の異なる待ち時間を、同じ変数の別々の既定値だけで表現しようとすると、こうした非対称な組み合わせの見落としが起きやすい。

15. **タイムアウト値のマージン調整は対症療法であり、根本原因(同期の欠如)を覆い隠すことがある。** 「実機・シムのタイムアウトを揃える」対応は今回の具体的な失敗は防ぐが、実機とシムが互いに独立して自走し位置が同期していない、という設計上の前提そのものは変えていない。マージンをどれだけ調整しても、根本的な位置ズレの可能性は残ることを認識しておく必要がある。

16. **今回の不具合は、シミュレーションが可能にした知見でもある。** 実機8秒/シム12秒という非対称なタイムアウト設定は、結果的に「モーターの個体差(旋回速度のバラつき)が大きい2台を組み合わせた」状況を模擬したテストケースになっていた。ばらつきの大きく異なるモーターを実機だけで意図的に調達・組み合わせて再現するのは難しいが、シムなら旋回タイミングをパラメータとして自由に変えられるため、この種の「個体差が大きい場合に現状の連携方法(leader/followerの自走+タイムアウト)で何が起きるか」を安価に調べられる。シミュレータは既知動作の代替検証手段であるだけでなく、実機では作りにくい作為的な条件でのテストケース生成手段としても活用できる。

**追記(再テスト結果)**: `--scanning-timeout`を実機・シムとも8秒に揃えた上でleader/follower入れ替えを再テストしたところ、正常に動作した。あわせてユーザーが目視観察したところ、シムは全体的に旋回が遅め(一様)、実機は旋回速度が不均一(場所によりムラがある)という違いが見られた。これは上記16.で述べた「モーター個体差の模擬」という見立てと整合する観察であり、実機側の不均一さは機械的要因(摩擦・ケーブル抵抗など)の可能性がある。将来、上記「保留した本質的な課題」(followerの位置追従制御)を検討する際は、この個体差・不均一さの実測値も参考になる。

## マイルストーン7: 実機SCAN_FAILEDの原因究明、マーカー色の赤→緑変更、scanning_timeout_secの見直し(完了)

### 経緯

可視化検証(`bridge/plot_scan.py`)の実地確認中、実機・シム双方の単体leader実行(`demo_real_leader.bash`/`demo_hako_leader.bash`)で`SCAN_FAILED`が発生することを発見した。

### シム側の原因(実証済み、詳細は別途メモリ記録)

CPU負荷が高い状態でシムを動かすと、`scanning_timeout_sec`の判定が`time.monotonic()`(壁時計)で行われる一方、旋回はHakoniwaのconductorが管理する**シミュレーション時刻**ベースで進むため、負荷が高いと(壁時計換算で)旋回が相対的に遅くなり、タイムアウトに間に合わなくなることがあると実証した(軽量条件0/5・重い条件1/5で`SCAN_FAILED`発生)。

### 状態機械図の確認

ユーザーから「`SCANNING`から`is_fired`で遷移する先が2つ(`SCAN_FAILED`と`WAIT_FOR_DETECTED_GRACE`)ある」との指摘があったが、Astah MCPでモデルデータを直接確認した結果、`[is_leader]`→`SCAN_FAILED`、`[!is_leader]`→`WAIT_FOR_DETECTED_GRACE`で矛盾なく排他分岐していた(コードとも一致)。図の矢印が密集して視覚的に紛らわしかっただけと判明。

### 実機側の原因: 赤マーカーのしきい値問題(実測で発見)

実機でタイムスタンプ付き・HSV生値付きのログを取得し、以下を実証した。

1. **チャタリング**: 赤のしきい値(`hue >= 340`)の境界(実際のマーカー色相339〜342付近)を、センサーノイズがまたぐたびに検出フラグが反転し、短時間に5回連続で反転(=旋回が停滞)することがあった。
2. **背景色との誤検出リスク**: 機体周辺の茶色パーツを実測したところ`hue=348〜353, sat=231〜243, val=188〜196`で、これは赤のしきい値条件(`hue>=340`かつ`sat>=40, val>=40`)を満たしてしまい、**茶色が「赤」として誤検出されうる**ことが判明した(青のしきい値`sat>=580`のような厳しい彩度条件が赤には無かったため)。

### マーカー色の選定と変更

黄色・緑を候補として実測(`libspikehat/examples/test_sensor.py`を使用、モーターを動かさない安全な確認)し、周辺の既知の色(水色hue198〜204、紫hue234〜240、青hue210〜270、茶色hue348〜353)との距離を比較した結果、緑(実測hue158〜170)を採用した。しきい値: `hue 145〜185, sat>=150, val>=50`。

変更箇所: `sonar_radar-zenoh-bridge/bridge/real_marker_detector.py`・`hako_marker_detector.py`、`sonar_radar/raspi/sonar_radar.py`(`is_red`→`is_green`)、`sonar_radar/mujoco_model/sonar_radar.xml`(`base_red_geom`のrgbaを緑相当に変更、HSV変換でhue≈167になるよう`0.020 0.250 0.200 1`に設定)。実機の物理マーカーブロックも緑に交換済み。実機・シム双方で緑マーカーの安定検出(チャタリングなし)を確認済み。

### scanning_timeout_secの見直し

マーカー変更後も、実機実測(タイムスタンプ付きログ)で1レッグの旋回時間が平均7.83秒・最大8.71秒(20回中6回が8秒超)と判明し、`scanning_timeout_sec=8秒`はほぼ余裕が無いことが実証された。「旋回継続しながらのGRACE状態」を追加する案も検討したが、ユーザーから「事実上タイムアウト延長と同じ」との指摘があり、シンプルに既定値を8→10秒に変更する対応を採用した(`sonar_radar_app.py`/`app_runner.py`/`run_real.py`/`run_hako.py`)。実機実測で6回連続`SCAN_FAILED`なしを確認済み。

### 残った技術的負債

- **マーカーのサブモデル名が色に基づく命名になっている**(Studio上の`marker_red`/`marker_blue`、`blender_export.py`のオブジェクト名検索、出力STLファイル名`radar_base_red.stl`、MuJoCo側の`base_red_geom`)。今回は色(rgba値)のみ変更し名前は据え置いたため、「red」という名前なのに実際は緑、という不整合が残っている。`blender_export.py`は名前(識別子)でパーツを検索しており色そのものは見ていないため動作に支障はないが、将来の混乱を避けるため、**Studio(.io)からMuJoCo XMLまで一貫して色ベースの名前(red/blue)を役割ベースの名前(left/right等)に統一する**リファクタリングを、別途まとまった作業として行うことで合意した。
- Studio(.io)モデル側のマーカー色変更(`marker_red`サブモデルの色編集)はユーザーが別途実施する。MuJoCo XML直接編集は、それまでの暫定処置。

### 得られた教訓

17. **色のしきい値設計では、対象色だけでなく周辺の全既知色との距離を確認する必要がある。** 赤マーカーのしきい値は「赤らしさ」だけを基準に決められており、機体周辺に存在する別の色(茶色)との誤検出リスクが見落とされていた。新しい色を選ぶ際は、既知の背景色・他パーツの色を実測し、候補色がそれら全てから十分離れているかを確認する必要がある。

18. **診断は理論より先に実測データで検証すべき。** 「タイムアウトが8秒でタイトすぎるのでは」という仮説も、「マーカーがチャタリングしているのでは」という仮説も、実際にタイムスタンプ付き・HSV生値付きのログを取ることで初めて実証できた。理論的な推測(壁時計/シミュレーション時刻の非対称性など)は方向性としては正しかったが、実測なしに対策を決めていたら誤った対応になっていた可能性がある。

19. **「旋回を止めずに待つ猶予」は実質的にタイムアウトの延長にすぎない。** GRACE状態(follower用)を模してleader用にも旋回継続の猶予状態を追加する案を検討したが、ユーザーから「事実上タイムアウト時間の延長と同じ」との指摘を受け、状態機械を複雑にせず単純にタイムアウト値を見直す対応に落ち着いた。安全機構としての振る舞いが同じなら、シンプルな実装を優先すべきという教訓。

20. **ビルド成果物を直接編集するのは、ソースを更新しない限り技術的負債になる。** MuJoCo XMLはStudio(.io)からBlender経由で生成される成果物だが、今回は緊急性を優先しXML側を直接編集した。ユーザーから「ライブラリにパッチしてソースコードは直さないのと同じ」との指摘があった通り、正式にはソース(Studio .io)側も更新し、ビルドパイプラインを通して整合性を保つ必要がある。
