"""BleakGATTServiceBlueRPC."""
from __future__ import annotations

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService

from .rpc.gatt_pb2 import BLEService


class BleakGATTServiceBlueRPC(BleakGATTService):
    """GATT Characteristic implementation for the BlueRPC backend."""

    handle_cpt = 0

    def __init__(self, obj: BLEService) -> None:
        """Init a BleakGATTServiceBlueRPC"""
        super().__init__(obj)  # type: ignore[no-untyped-call]
        self.__characteristics: list[BleakGATTCharacteristic] = []
        self.__handle: int = BleakGATTServiceBlueRPC.handle_cpt
        BleakGATTServiceBlueRPC.handle_cpt += 1

    @property
    def handle(self) -> int:
        """Integer handle of this service."""
        return self.__handle

    @property
    def uuid(self) -> str:
        """UUID for this service."""
        return self.obj.uuid

    @property
    def characteristics(self) -> list[BleakGATTCharacteristic]:
        """List of characteristics for this service."""
        return self.__characteristics

    def add_characteristic(self, characteristic: BleakGATTCharacteristic) -> None:
        """Add a :py:class:`~BleakGATTCharacteristicBlueRPC` to the service.

        Should not be used by end user, but rather by `bleak` itself.
        """
        self.__characteristics.append(characteristic)
