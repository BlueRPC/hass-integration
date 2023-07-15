"""BleakGATTDescriptorBlueRPC."""
from __future__ import annotations

from bleak.backends.descriptor import BleakGATTDescriptor

from .rpc.gatt_pb2 import BLEDescriptor


class BleakGATTDescriptorBlueRPC(BleakGATTDescriptor):
    """GATT Descriptor implementation for BlueRPC backend."""

    handle_cpt = 0

    def __init__(
        self,
        obj: BLEDescriptor,
        characteristic_uuid: str,
        characteristic_handle: int,
    ) -> None:
        """Init a BleakGATTDescriptorBlueRPC."""
        super().__init__(obj)
        self.__characteristic_uuid: str = characteristic_uuid
        self.__characteristic_handle: int = characteristic_handle
        self.__handle: int = BleakGATTDescriptorBlueRPC.handle_cpt
        BleakGATTDescriptorBlueRPC.handle_cpt += 1

    @property
    def characteristic_handle(self) -> int:
        """Handle for the characteristic that this descriptor belongs to."""
        return self.__characteristic_handle

    @property
    def characteristic_uuid(self) -> str:
        """UUID for the characteristic that this descriptor belongs to."""
        return self.__characteristic_uuid

    @property
    def uuid(self) -> str:
        """UUID for this descriptor."""
        return self.obj.uuid

    @property
    def handle(self) -> int:
        """Integer handle for this descriptor."""
        return self.__handle
