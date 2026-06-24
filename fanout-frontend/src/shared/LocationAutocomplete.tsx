import { useEffect, useRef, useState } from "react";
import { searchLocations, type LocationSuggestion } from "./api";

// Location typeahead for the Local SEO new-session form, mirroring the Local SEO
// writer's location autocomplete. Debounced DataForSEO suggestions served by the
// /fanout/locations wrapper, scoped by `country` (the selected market) so it
// autocompletes for everyone; `clientId` is an optional fallback scope.
export function LocationAutocomplete(p: {
  country?: string;
  clientId?: string | null;
  // Committed location (a value means a suggestion was picked); used only to mark
  // the field as resolved.
  value: string;
  inputValue: string;
  onSelect: (loc: LocationSuggestion) => void;
  onInputChange: (raw: string) => void;
  onClear: () => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [suggestions, setSuggestions] = useState<LocationSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  // Close the dropdown on an outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const canSearch = Boolean(p.country || p.clientId);

  function handleInput(raw: string) {
    p.onInputChange(raw);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!canSearch || raw.trim().length < 2) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const rows = await searchLocations(raw.trim(), {
          country: p.country,
          clientId: p.clientId,
        });
        setSuggestions(rows);
        setOpen(true);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    }, 200);
  }

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <input
        className="input"
        value={p.inputValue}
        disabled={p.disabled}
        placeholder={p.placeholder ?? "Start typing a city or area…"}
        onChange={(e) => handleInput(e.target.value)}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        autoComplete="off"
      />
      {p.value && p.value === p.inputValue && (
        <button
          type="button"
          className="link-btn"
          style={{ position: "absolute", right: 8, top: 10 }}
          onClick={() => {
            setSuggestions([]);
            setOpen(false);
            p.onClear();
          }}
        >
          Clear
        </button>
      )}
      {open && (loading || suggestions.length > 0) && (
        <div
          style={{
            position: "absolute",
            zIndex: 20,
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            background: "var(--card, #fff)",
            border: "1px solid var(--input, #d4d4d8)",
            borderRadius: 8,
            boxShadow: "0 6px 24px rgba(0,0,0,0.10)",
            overflow: "hidden",
          }}
        >
          {loading && suggestions.length === 0 ? (
            <div className="muted" style={{ padding: "8px 12px", fontSize: 13 }}>
              Searching…
            </div>
          ) : (
            suggestions.map((s) => (
              <button
                key={s.location_code}
                type="button"
                className="location-option"
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "8px 12px",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 14,
                }}
                onClick={() => {
                  p.onSelect(s);
                  setOpen(false);
                }}
              >
                {s.location_name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
