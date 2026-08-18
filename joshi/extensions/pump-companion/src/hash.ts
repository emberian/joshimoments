const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;

export type Sha256Id = `sha256:${string}`;

export function isSha256Id(value: string): value is Sha256Id {
  return SHA256_PATTERN.test(value);
}

export async function sha256Id(bytes: Uint8Array): Promise<Sha256Id> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  const hex = [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `sha256:${hex}`;
}

export async function sha256Utf8(value: string): Promise<Sha256Id> {
  return sha256Id(new TextEncoder().encode(value));
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let offset = 0; offset < bytes.byteLength; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  if (bytesToBase64(bytes) !== value) {
    throw new Error("response body is not canonical base64");
  }
  return bytes;
}
