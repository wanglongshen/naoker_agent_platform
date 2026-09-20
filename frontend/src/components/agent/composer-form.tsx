"use client";

import React, { type ReactNode } from "react";
import { Form } from "antd";

type Props = {
  action: (formData: FormData) => void | Promise<void>;
  className: string;
  id: string;
  children: ReactNode;
};

export default function ComposerForm({ action, className, id, children }: Props) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        action(new FormData(e.currentTarget));
      }}
      className={className}
      id={id}
    >
      <Form component={false} layout="vertical">
        {children}
      </Form>
    </form>
  );
}
