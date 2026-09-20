"use client";

import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { hasPermission, USER_ASSIGN_ROLE } from "@/lib/permissions";
import type { CurrentUser } from "@/types/auth";
import type { RoleReference } from "@/types/role";
import type { UserListItem } from "@/types/user";

interface UserFormDialogProps {
  open: boolean;
  user: UserListItem | null;
  currentUser: CurrentUser;
  assignableRoles?: RoleReference[];
  onClose: () => void;
  onSuccess: () => void;
}

const PASSWORD_RULE = /^(?=.*[a-zA-Z])(?=.*\d).{8,}$/;

function validatePassword(password: string): string | null {
  if (!password) return "Password is required.";
  if (password.length < 8) {
    return "Password must be at least 8 characters with a letter and a digit.";
  }
  if (!PASSWORD_RULE.test(password)) {
    return "Password must include at least one letter and one digit.";
  }
  return null;
}

export default function UserFormDialog({
  open,
  user,
  currentUser,
  assignableRoles,
  onClose,
  onSuccess,
}: UserFormDialogProps) {
  const isCreate = !user;
  const canAssignRoles =
    hasPermission(currentUser, USER_ASSIGN_ROLE) &&
    assignableRoles &&
    assignableRoles.length > 0;

  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("active");
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  function resetForm() {
    setUsername("");
    setDisplayName(user?.display_name ?? "");
    setEmail(user?.email ?? "");
    setPhone(user?.phone ?? "");
    setPassword("");
    setStatus("active");
    setRoleIds([]);
    setError("");
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    if (isCreate) {
      const pwError = validatePassword(password);
      if (pwError) {
        setError(pwError);
        return;
      }
      if (!username.trim()) {
        setError("Username is required.");
        return;
      }
    }
    if (!displayName.trim()) {
      setError("Display name is required.");
      return;
    }

    const body: Record<string, unknown> = {};
    if (isCreate) {
      body.username = username.trim();
      body.status = status;
      body.password = password;
    }
    body.display_name = displayName.trim();
    if (email) body.email = email;
    else body.email = null;
    if (phone) body.phone = phone;
    else body.phone = null;
    if (canAssignRoles) body.role_ids = roleIds;

    setSaving(true);
    try {
      await api(isCreate ? "/api/users" : `/api/users/${user!.id}`, {
        method: isCreate ? "POST" : "PUT",
        body: JSON.stringify(body),
      });
      resetForm();
      onClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.status) {
          case 400:
            setError(err.message || "Invalid input.");
            break;
          case 403:
            setError("You do not have permission to perform this action.");
            break;
          case 404:
            setError("User not found.");
            break;
          case 409:
            setError("Username, email, or phone already exists.");
            break;
          case 422:
            setError(err.message || "Invalid input. Please check your entries.");
            break;
          default:
            setError(err.message || "An error occurred.");
        }
      } else {
        setError("An error occurred. Please try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog">
        <h2>{isCreate ? "Create User" : "Edit User"}</h2>
        {error && <div className="alert alert-error" role="alert">{error}</div>}
        <form onSubmit={handleSubmit} noValidate>
          {isCreate && (
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={saving}
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="password">Initial Password</label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={saving}
                  required
                />
              </div>
            </div>
          )}
          <div className="form-group">
            <label htmlFor="displayName">Display Name</label>
            <input
              id="displayName"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={saving}
              required
            />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={saving}
              />
            </div>
            <div className="form-group">
              <label htmlFor="phone">Phone</label>
              <input
                id="phone"
                type="text"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                disabled={saving}
              />
            </div>
          </div>
          {isCreate && (
            <div className="form-group">
              <label htmlFor="status">Status</label>
              <select
                id="status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                disabled={saving}
              >
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
          )}
          {canAssignRoles && (
            <div className="form-group">
              <label htmlFor="roles">Roles</label>
              <select
                id="roles"
                multiple
                value={roleIds}
                onChange={(e) =>
                  setRoleIds(
                    Array.from(e.target.selectedOptions, (opt) => opt.value)
                  )
                }
                disabled={saving}
                style={{ minHeight: "80px" }}
              >
                {assignableRoles!.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
