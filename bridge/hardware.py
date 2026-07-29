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
    def starter_is_pushed(self) -> bool:
        """starter(フォースセンサー等)が押されているか。starter未使用ならFalse。"""

    @abc.abstractmethod
    def close(self) -> None:
        """保持しているハードウェア接続を解放する。"""


class RealHardware(RadarHardware):
    """実機のハードウェアアクセス(libspikehat経由)。

    Build HATのファームウェアロードはinitialize()内で行う(SonarRadarAppの
    INITのentry、broker.open()より後)。RealRadarBase/RealStarterは
    Build HATへの同じシリアル接続(hat)を共有する必要があるため、
    real_hat.create_real_hat()で1つだけ構築して両方に渡す
    (real_hat.pyのモジュールdocstring参照)。

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

    def initialize(self) -> None:
        if self._use_radar_base or self._use_starter:
            from real_hat import create_real_hat

            self._hat = create_real_hat()
        if self._use_radar_base:
            from real_radar_base import RealRadarBase

            self._radar_base = RealRadarBase(self._hat)
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

    def starter_is_pushed(self) -> bool:
        if self._starter is None:
            return False
        return self._starter.is_pushed()

    def close(self) -> None:
        if self._hat is not None:
            self._hat.close()


class HakoHardware(RadarHardware):
    """シム(MuJoCo/Hakoniwa plant)のハードウェアアクセス。

    hako_hat(HakoSpikeHat)自体はhakopyのasset登録に必要なため、
    呼び出し側(run_hako.py)がinitialize()より前に構築して渡す
    (この構築だけはSonarRadarAppのINITタイミングに合わせられない、
    hakopyフレームワーク側の制約)。HakoRadarBase/HakoStarterの構築は
    軽量・即時のため、実機のような遅延の必要は無いが、対称性のため
    initialize()内で行う。
    """

    def __init__(self, hako_hat, use_starter: bool) -> None:
        self._hako_hat = hako_hat
        self._use_starter = use_starter
        self._radar_base = None
        self._starter = None

    def initialize(self) -> None:
        from hako_radar_base import HakoRadarBase

        self._radar_base = HakoRadarBase(self._hako_hat)
        if self._use_starter:
            from hako_starter import HakoStarter

            self._starter = HakoStarter(self._hako_hat)

    def radar_base_calibrate(self) -> None:
        self._radar_base.calibrate()

    def radar_base_is_calibrated(self) -> bool:
        return self._radar_base.is_calibrated()

    def starter_is_pushed(self) -> bool:
        if self._starter is None:
            return False
        return self._starter.is_pushed()

    def close(self) -> None:
        pass  # hako_hatのライフサイクルは呼び出し側(hakopy asset)が持つ
