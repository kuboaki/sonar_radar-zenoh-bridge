"""hardware — 実機/シムのハードウェアアクセスを差し替え可能にする共通インターフェース。

libspikehat/libspikehat_sim が sonar_radar 本体向けに提供している
「同じヘッダ(libspikehat.h)に対する実機/シムの2実装」というパターンを、
sonar_radar-zenoh-bridge の呼び出し側スクリプト(run_real.py/run_hako.py)
のハードウェア配線にも適用したもの。RadarHardware が libspikehat.h に
相当する契約で、RealHardware/HakoHardware がその実機/シム実装にあたる。

SonarRadarApp自体は今まで通り、hardware_initialize/radar_base_calibrate/
radar_base_is_calibrated/starter_is_pushedを4つの独立したコールバックと
して個別に注入可能にする設計を変えない(状態機械図が個別のガード/エフェクト
関数として設計しているため、ここを1個のhardwareオブジェクトにまとめるのは
図の設計意図から外れる)。統一するのはあくまでrun_real.py/run_hako.pyが
「どちらの実装を選んで束縛するか」という、呼び出し側スクリプト内の配線だけ。
"""

from __future__ import annotations

import abc


class RadarHardware(abc.ABC):
    """実機/シムで共通のハードウェアアクセス契約。

    initialize()はSonarRadarAppのINITのentryでhardware_initialize()として
    呼ばれる想定(実機ではBuild HATのファームウェアロード等でブロッキング
    しうる処理を含む)。close()は呼び出し側スクリプトのfinallyで呼ぶ
    (SonarRadarApp自体はハードウェアの生成・破棄に関与しない、呼び出し側
    の責務)。
    """

    @abc.abstractmethod
    def initialize(self) -> None:
        """ハードウェアを初期化する(重い/ブロッキングな処理を含みうる)。"""

    @abc.abstractmethod
    def radar_base_calibrate(self) -> None:
        """radar_base(旋回モーター)のキャリブレーションを開始する(非同期)。"""

    @abc.abstractmethod
    def radar_base_is_calibrated(self) -> bool:
        """radar_baseのキャリブレーションが完了したか。"""

    @abc.abstractmethod
    def radar_base_run(self) -> None:
        """radar_baseの継続旋回を開始する(冪等、既に回転中なら何もしない)。"""

    @abc.abstractmethod
    def radar_base_stop(self) -> None:
        """radar_baseの継続旋回を停止する。"""

    @abc.abstractmethod
    def radar_base_invert_direction(self) -> None:
        """radar_baseの回転方向を反転する(止めずに切り替える)。"""

    @abc.abstractmethod
    def radar_base_get_position(self) -> int:
        """radar_baseの現在のモーター角度(度、生値)を返す。"""

    @abc.abstractmethod
    def radar_base_get_dome_angle(self) -> float:
        """radar_baseの現在のドーム角度(度)を返す。"""

    @abc.abstractmethod
    def marker_detector_is_detected(self) -> bool:
        """marker_detector(色センサー)がマーカーを新たに検出したか(立ち上がりエッジ)。"""

    @abc.abstractmethod
    def starter_is_pushed(self) -> bool:
        """starter(フォースセンサー等)が押されているか。starter未使用ならFalse。"""

    def scanner_get_distance(self) -> int:
        """scanner(距離センサー)の現在値(mm)を返す。既定は未実装のダミー値(0)。

        distance_mmの実センサー配線は実機(RealHardware)のみ対応済み(#16)。
        シム(HakoHardware)側はまだ未対応のため、既定実装(このメソッド)を
        オーバーライドせずに使う。
        """
        return 0

    @abc.abstractmethod
    def close(self) -> None:
        """保持しているハードウェア接続を解放する。"""


class RealHardware(RadarHardware):
    """実機のハードウェアアクセス(libspikehat経由)。

    Build HATのファームウェアロードはinitialize()内で行う(SonarRadarAppの
    INITのentry、broker.open()より後)。RealRadarBase/RealStarter/
    RealMarkerDetectorは、Build HATへの同じシリアル接続(hat)を共有する
    必要があるため、real_hat.create_real_hat()で1つだけ構築して渡す
    (real_hat.pyのモジュールdocstring参照)。

    marker_detectorはradar_baseと同じ物理ドームに載っているため、
    use_radar_baseフラグと連動させる(個別のフラグは設けない)。

    radar_base/starterを使わない場合(コンストラクタでFalse指定)は、
    従来のスタブと同じ既定値(radar_base_is_calibrated()は即True、
    starter_is_pushed()は常にFalse)を返す。
    """

    def __init__(self, use_radar_base: bool, use_starter: bool) -> None:
        self._use_radar_base = use_radar_base
        self._use_starter = use_starter
        self._hat = None
        self._radar_base = None
        self._starter = None
        self._marker_detector = None
        self._scanner = None

    def initialize(self) -> None:
        if self._use_radar_base or self._use_starter:
            from real_hat import create_real_hat

            self._hat = create_real_hat()
        if self._use_radar_base:
            from real_radar_base import RealRadarBase
            from real_marker_detector import RealMarkerDetector
            from real_scanner import RealScanner

            self._radar_base = RealRadarBase(self._hat)
            self._marker_detector = RealMarkerDetector(self._hat)
            self._scanner = RealScanner(self._hat)
        if self._use_starter:
            from real_starter import RealStarter

            self._starter = RealStarter(self._hat)

    def radar_base_calibrate(self) -> None:
        if self._radar_base is not None:
            self._radar_base.calibrate()

    def radar_base_is_calibrated(self) -> bool:
        if self._radar_base is None:
            return True  # 既定スタブ(radar_base未使用時は即完了扱い)
        return self._radar_base.is_calibrated()

    def radar_base_run(self) -> None:
        if self._radar_base is not None:
            self._radar_base.run()

    def radar_base_stop(self) -> None:
        if self._radar_base is not None:
            self._radar_base.stop()

    def radar_base_invert_direction(self) -> None:
        if self._radar_base is not None:
            self._radar_base.invert_direction()

    def radar_base_get_position(self) -> int:
        if self._radar_base is None:
            return 0
        return self._radar_base.get_position()

    def radar_base_get_dome_angle(self) -> float:
        if self._radar_base is None:
            return 0.0
        return self._radar_base.get_dome_angle()

    def marker_detector_is_detected(self) -> bool:
        if self._marker_detector is None:
            return False
        return self._marker_detector.is_detected()

    def starter_is_pushed(self) -> bool:
        if self._starter is None:
            return False
        return self._starter.is_pushed()

    def scanner_get_distance(self) -> int:
        if self._scanner is None:
            return 0
        return self._scanner.get_distance()

    def close(self) -> None:
        if self._hat is not None:
            self._hat.close()


class HakoHardware(RadarHardware):
    """シム(MuJoCo/Hakoniwa plant)のハードウェアアクセス。

    hako_hat(HakoSpikeHat)自体はhakopyのasset登録に必要なため、
    呼び出し側(run_hako.py)がinitialize()より前に構築して渡す
    (この構築だけはSonarRadarAppのINITタイミングに合わせられない、
    hakopyフレームワーク側の制約)。HakoRadarBase/HakoStarter/
    HakoMarkerDetectorの構築は軽量・即時のため、実機のような遅延の
    必要は無いが、対称性のためinitialize()内で行う。marker_detectorは
    radar_baseと同じく常に構築する(実機のuse_radar_baseフラグに相当する
    ものは無く、シムのradar_baseは既定で常に有効なため)。
    """

    def __init__(self, hako_hat, use_starter: bool) -> None:
        self._hako_hat = hako_hat
        self._use_starter = use_starter
        self._radar_base = None
        self._starter = None
        self._marker_detector = None

    def initialize(self) -> None:
        from hako_radar_base import HakoRadarBase
        from hako_marker_detector import HakoMarkerDetector

        self._radar_base = HakoRadarBase(self._hako_hat)
        self._marker_detector = HakoMarkerDetector(self._hako_hat)
        if self._use_starter:
            from hako_starter import HakoStarter

            self._starter = HakoStarter(self._hako_hat)

    def radar_base_calibrate(self) -> None:
        self._radar_base.calibrate()

    def radar_base_is_calibrated(self) -> bool:
        return self._radar_base.is_calibrated()

    def radar_base_run(self) -> None:
        self._radar_base.run()

    def radar_base_stop(self) -> None:
        self._radar_base.stop()

    def radar_base_invert_direction(self) -> None:
        self._radar_base.invert_direction()

    def radar_base_get_position(self) -> int:
        return self._radar_base.get_position()

    def radar_base_get_dome_angle(self) -> float:
        return self._radar_base.get_dome_angle()

    def marker_detector_is_detected(self) -> bool:
        return self._marker_detector.is_detected()

    def starter_is_pushed(self) -> bool:
        if self._starter is None:
            return False
        return self._starter.is_pushed()

    def close(self) -> None:
        pass  # hako_hatのライフサイクルは呼び出し側(hakopy asset)が持つ
