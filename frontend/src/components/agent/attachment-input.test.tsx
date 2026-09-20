import { describe, it, expect, vi } from "vitest";
import { createRef, useState } from "react";
import { act, render } from "@testing-library/react";
import AttachmentInput, { FileCardGrid, type AttachmentInputHandle, type PendingFile } from "./attachment-input";

function renderInput() {
  const ref = createRef<AttachmentInputHandle>();
  const onPendingFilesChange = vi.fn();

  function Harness() {
    const [files, setFiles] = useState<PendingFile[]>([]);
    return (
      <AttachmentInput
        ref={ref}
        pendingFiles={files}
        onPendingFilesChange={(next) => {
          setFiles(next);
          onPendingFilesChange(next);
        }}
      />
    );
  }

  const utils = render(<Harness />);
  return { ref, onPendingFilesChange, ...utils };
}

function addFilesThroughRef(ref: React.RefObject<AttachmentInputHandle | null>, files: File[]) {
  let result: string | null = null;
  act(() => {
    result = ref.current?.addFiles(files) ?? null;
  });
  return result;
}

describe("AttachmentInput drag-drop (addFiles)", () => {
  it("accepts dropped files into pending list", () => {
    const { ref, onPendingFilesChange } = renderInput();

    const file = new File(["hello"], "report.txt", { type: "text/plain" });
    const result = addFilesThroughRef(ref, [file]);

    expect(result).toBeNull();
    expect(onPendingFilesChange).toHaveBeenCalledWith([
      expect.objectContaining({ file }),
    ]);
  });

  it("rejects files over 20MB", () => {
    const { ref, onPendingFilesChange, getByRole } = renderInput();

    const big = new File(["x"], "big.bin", { type: "application/octet-stream" });
    Object.defineProperty(big, "size", { value: 21_000_000 });
    const result = addFilesThroughRef(ref, [big]);

    expect(result).toContain("超过 20 MB");
    expect(onPendingFilesChange).not.toHaveBeenCalled();
    expect(getByRole("alert")).toBeInTheDocument();
  });

  it("allows any file type", () => {
    const { ref, onPendingFilesChange } = renderInput();

    const pdf = new File(["%PDF"], "doc.pdf", { type: "application/pdf" });
    const png = new File(["PNG"], "img.png", { type: "image/png" });
    const result = addFilesThroughRef(ref, [pdf, png]);

    expect(result).toBeNull();
    expect(onPendingFilesChange).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ file: expect.objectContaining({ name: "doc.pdf" }) }),
        expect.objectContaining({ file: expect.objectContaining({ name: "img.png" }) }),
      ]),
    );
  });

  it("rejects adding files beyond the 10-file limit", () => {
    const { ref, onPendingFilesChange, getByRole } = renderInput();

    const first = new File(["a"], "a.txt", { type: "text/plain" });
    const firstResult = addFilesThroughRef(ref, Array.from({ length: 10 }, () => first));
    expect(firstResult).toBeNull();

    const extra = new File(["b"], "b.txt", { type: "text/plain" });
    const result = addFilesThroughRef(ref, [extra]);

    expect(result).toContain("最多上传 10 个文件");
    expect(onPendingFilesChange).toHaveBeenCalledTimes(1);
    expect(getByRole("alert")).toBeInTheDocument();
  });
});

describe("FileCardGrid", () => {
  function makeFile(name: string, size = 8192, type = "text/markdown"): File {
    return new File(["x".repeat(size)], name, { type });
  }

  it("renders file cards with name, format and size", () => {
    const { container } = render(
      <FileCardGrid files={[{ file: makeFile("脑壳儿_Brief输入模板.md"), key: "k1" }]} onRemove={() => {}} />,
    );
    const card = container.querySelector(".composer-file-card");
    expect(card).toBeTruthy();
    expect(card!.querySelector(".composer-file-card-name")!.textContent).toContain("脑壳儿_Brief输入模板.md");
    expect(card!.querySelector(".composer-file-card-meta")!.textContent).toContain("Markdown");
    expect(card!.querySelector(".composer-file-card-meta")!.textContent).toContain("8KB");
  });

  it("marks icon type via data attribute", () => {
    const { container } = render(
      <FileCardGrid files={[{ file: makeFile("plan.docx", 1024, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), key: "k2" }]} onRemove={() => {}} />,
    );
    const icon = container.querySelector(".composer-file-card-icon");
    expect(icon?.getAttribute("data-file-icon")).toBe("doc");
  });

  it("keeps remove button working", () => {
    const onRemove = vi.fn();
    const { container } = render(
      <FileCardGrid files={[{ file: makeFile("a.md"), key: "k1" }]} onRemove={onRemove} />,
    );
    const buttons = Array.from(container.querySelectorAll("button"));
    const remove = buttons.find((b) => b.textContent?.includes("×"));
    expect(remove).toBeTruthy();
    remove!.click();
    expect(onRemove).toHaveBeenCalledWith("k1");
  });
});
