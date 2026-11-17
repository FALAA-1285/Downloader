import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MediaItem } from "@/types";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { SelectAllRow } from "@/components/media-preview/select-all";
import { SettingsView } from "@/components/layout/settings-view";

afterEach(cleanup);

const item = (id: string, downloadable = true): MediaItem => ({
  id,
  type: "image",
  filename: `${id}.png`,
  url: `https://a.example/${id}.png`,
  mime_type: "image/png",
  size: 10,
  downloadable,
});

describe("ConfirmDialog (L-15)", () => {
  it("menjalankan aksi hanya setelah dikonfirmasi", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <ConfirmDialog
        title="Hapus riwayat ini?"
        description="Permanen."
        confirmLabel="Hapus"
        onConfirm={onConfirm}
        trigger={<button type="button">Buka</button>}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Buka" }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Batal" }));
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Buka" }));
    await user.click(screen.getByRole("button", { name: "Hapus" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("tetap terbuka dan menampilkan error bila aksi gagal", async () => {
    render(
      <ConfirmDialog
        title="Hapus?"
        description="Permanen."
        confirmLabel="Hapus"
        onConfirm={() => Promise.reject(new Error("Server menolak."))}
        trigger={<button type="button">Buka</button>}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Buka" }));
    await user.click(screen.getByRole("button", { name: "Hapus" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Server menolak.");
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });
});

describe("SelectAllRow", () => {
  it("menunjukkan status sebagian terpilih dan hanya memilih item yang bisa diunduh", async () => {
    const onSetMany = vi.fn();
    const items = [item("a"), item("b"), item("c", false)];
    const { rerender } = render(<SelectAllRow items={items} selected={new Set(["a"])} onSetMany={onSetMany} />);

    const box = screen.getByRole("checkbox");
    expect(box.getAttribute("aria-checked")).toBe("mixed");
    expect(screen.getByText("1 tidak dapat diunduh")).toBeTruthy();

    await userEvent.setup().click(box);
    expect(onSetMany).toHaveBeenCalledWith(["a", "b"], true);

    rerender(<SelectAllRow items={items} selected={new Set(["a", "b"])} onSetMany={onSetMany} />);
    expect(screen.getByRole("checkbox").getAttribute("aria-checked")).toBe("true");
  });
});

describe("SettingsView & Mode Gelap", () => {
  it("merender opsi tema dan dapat berpindah ke mode gelap", async () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    render(<SettingsView />);
    expect(screen.getByRole("heading", { name: "Tema" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Server" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Adapter sumber" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Riwayat" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Tentang" })).toBeTruthy();

    const darkLabel = screen.getByText("Gelap");
    await userEvent.setup().click(darkLabel);
    expect(document.documentElement.dataset.theme).toBe("dark");

    const lightLabel = screen.getByText("Terang");
    await userEvent.setup().click(lightLabel);
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
