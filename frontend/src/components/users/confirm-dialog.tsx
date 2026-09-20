"use client";

import { Modal } from "antd";
import { copy } from "@/lib/copy";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  isDestructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  isDestructive,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  return (
    <Modal
      title={title}
      open={open}
      onOk={onConfirm}
      onCancel={onClose}
      okText={confirmLabel}
      cancelText={copy.common.cancel}
      okButtonProps={{ danger: isDestructive }}
      destroyOnHidden
    >
      <p>{message}</p>
    </Modal>
  );
}
