import WebSocket from "ws";

type RuntimeSocketEnvelope = {
  socket: WebSocket;
  userId: string;
  deviceId: string;
};

export class RealtimeHub {
  private readonly runtimeSockets = new Map<string, RuntimeSocketEnvelope>();

  public attachRuntime(input: RuntimeSocketEnvelope): void {
    const existing = this.runtimeSockets.get(input.deviceId);

    if (existing && existing.socket !== input.socket) {
      existing.socket.close(4001, "replaced");
    }

    this.runtimeSockets.set(input.deviceId, input);
  }

  public detachRuntime(deviceId: string): void {
    this.runtimeSockets.delete(deviceId);
  }

  public isRuntimeConnected(deviceId: string): boolean {
    const connection = this.runtimeSockets.get(deviceId);
    return Boolean(connection && connection.socket.readyState === WebSocket.OPEN);
  }

  public sendToRuntime(deviceId: string, message: unknown): boolean {
    const connection = this.runtimeSockets.get(deviceId);

    if (!connection || connection.socket.readyState !== WebSocket.OPEN) {
      return false;
    }

    connection.socket.send(JSON.stringify(message));
    return true;
  }
}
