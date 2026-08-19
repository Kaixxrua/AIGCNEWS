package mcpapp

import (
	"fmt"
	"sort"
	"strings"
	"unicode/utf8"

	"aigcnews/mcp-go/internal/jsonx"
)

// PaperDetailRepository reads one public indexed document. A nil row means the
// id was valid but no public document matched it; storage errors remain behind
// the tool boundary and are intentionally masked by dispatch.call.
type PaperDetailRepository interface {
	GetPaperDetail(paperID string) (*DocumentRow, error)
}

type PaperDetailService struct {
	repository PaperDetailRepository
	documents  DocumentsService // shared public projection/attribution semantics
}

func NewPaperDetailService(repository PaperDetailRepository, publicBaseURL string) *PaperDetailService {
	return &PaperDetailService{
		repository: repository,
		documents:  DocumentsService{publicBaseURL: publicBaseURL},
	}
}

// Get implements get_paper_detail. Validation mirrors GetPaperDetailInput:
// strict string, strip whitespace, 1..128 characters, and extra=forbid.
func (s *PaperDetailService) Get(arguments map[string]any) (any, error) {
	paperID, err := validatePaperDetailArgs(arguments)
	if err != nil {
		return nil, err
	}
	row, err := s.repository.GetPaperDetail(paperID)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, ToolInputError{Message: fmt.Sprintf("Document %s not found.", pythonStringRepr(paperID))}
	}
	return jsonx.Object{
		{Key: "item", Value: s.documents.publicDocument(*row)},
		{Key: "attribution", Value: "Data provided by AIGC Radar · " + s.documents.attributionBase()},
	}, nil
}

func validatePaperDetailArgs(arguments map[string]any) (string, error) {
	var failures []string
	var paperID string

	raw, present := arguments["paper_id"]
	switch {
	case !present:
		failures = append(failures, "paper_id: Field required")
	default:
		value, ok := raw.(string)
		if !ok {
			failures = append(failures, "paper_id: Input should be a valid string")
		} else {
			value = strings.TrimSpace(value)
			switch length := utf8.RuneCountInString(value); {
			case length < 1:
				failures = append(failures, "paper_id: String should have at least 1 character")
			case length > 128:
				failures = append(failures, "paper_id: String should have at most 128 characters")
			default:
				paperID = value
			}
		}
	}

	var extras []string
	for key := range arguments {
		if key != "paper_id" {
			extras = append(extras, key)
		}
	}
	sort.Strings(extras)
	for _, key := range extras {
		failures = append(failures, key+": Extra inputs are not permitted")
	}
	if len(failures) > 0 {
		return "", ToolInputError{Message: strings.Join(failures, "; ")}
	}
	return paperID, nil
}

// pythonStringRepr covers the repr form used in the not-found error. IDs are
// normally arXiv slugs, but choosing the quote character and escaping control
// characters keeps error text deterministic for arbitrary valid IDs too.
func pythonStringRepr(value string) string {
	quote := byte('\'')
	if strings.Contains(value, "'") && !strings.Contains(value, `"`) {
		quote = '"'
	}
	var out strings.Builder
	out.WriteByte(quote)
	for _, r := range value {
		switch r {
		case '\\':
			out.WriteString(`\\`)
		case '\n':
			out.WriteString(`\n`)
		case '\r':
			out.WriteString(`\r`)
		case '\t':
			out.WriteString(`\t`)
		case '\b':
			out.WriteString(`\b`)
		case '\f':
			out.WriteString(`\f`)
		default:
			if r == rune(quote) {
				out.WriteByte('\\')
			}
			switch {
			case r < 0x20 || r == 0x7f || (r >= 0x80 && r <= 0xff):
				fmt.Fprintf(&out, `\x%02x`, r)
			case r == 0x2028 || r == 0x2029:
				fmt.Fprintf(&out, `\u%04x`, r)
			default:
				out.WriteRune(r)
			}
		}
	}
	out.WriteByte(quote)
	return out.String()
}

func NewPaperDetailHandlers(repository PaperDetailRepository, publicBaseURL string) Handlers {
	service := NewPaperDetailService(repository, publicBaseURL)
	return Handlers{"get_paper_detail": service.Get}
}
