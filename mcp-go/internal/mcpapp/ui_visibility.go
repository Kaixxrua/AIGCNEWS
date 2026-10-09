package mcpapp

// UIDeprecatedLookup is shared by template/icon discovery and direct lookup.
// Tests with a static catalog may omit it; the server always supplies the DB lookup.
type UIDeprecatedLookup func() (map[string]bool, error)

func (lookup UIDeprecatedLookup) ids() (map[string]bool, error) {
	if lookup == nil {
		return nil, nil
	}
	return lookup()
}
