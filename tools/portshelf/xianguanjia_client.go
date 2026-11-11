package main

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	xgjAPIOrigin       = "https://open.goofish.pro"
	xgjResponseLimit   = 2 << 20
	xgjRequestLimit    = 256 << 10
	xgjRequestTimeout  = 30 * time.Second
	xgjRequestInterval = 500 * time.Millisecond
	xgjShopsPath       = "/api/open/user/authorize/list"
	xgjAddressesPath   = "/api/open/user/address/list"
	xgjCategoriesPath  = "/api/open/product/category/list"
	xgjPropertiesPath  = "/api/open/product/pv/list"
	xgjProductsPath    = "/api/open/product/list"
	xgjProductPath     = "/api/open/product/detail"
	xgjCreatePath      = "/api/open/product/create"
	xgjPublishPath     = "/api/open/product/publish"
)

type XGJCredentials struct {
	AppKey    string `json:"appKey"`
	AppSecret string `json:"appSecret"`
}

func validXGJCredentials(credentials XGJCredentials) bool {
	if len(credentials.AppKey) < 1 || len(credentials.AppKey) > 19 || credentials.AppKey[0] == '0' {
		return false
	}
	for _, c := range credentials.AppKey {
		if c < '0' || c > '9' {
			return false
		}
	}
	if key, err := strconv.ParseInt(credentials.AppKey, 10, 64); err != nil || key <= 0 {
		return false
	}
	if len(credentials.AppSecret) < 1 || len(credentials.AppSecret) > 256 {
		return false
	}
	for _, c := range credentials.AppSecret {
		if c < 0x21 || c > 0x7e {
			return false
		}
	}
	return true
}

// Ambiguous means the server may have performed the requested write. Callers
// must reconcile a create/publish by reading before considering another write.
// Message is always local text: provider bodies and signed URLs are never kept.
type xgjError struct {
	Kind      string
	Code      int64
	Ambiguous bool
	Message   string
	cause     error
}

func (e *xgjError) Error() string {
	if e.Code != 0 {
		return fmt.Sprintf("%s（代码 %d）", e.Message, e.Code)
	}
	return e.Message
}

func (e *xgjError) Unwrap() error { return e.cause }

func xgjLocalError(kind, message string) error {
	return &xgjError{Kind: kind, Message: message}
}

func xgjInvalidResponse() error {
	return &xgjError{Kind: "invalid_response", Ambiguous: true, Message: "闲管家返回的数据不完整，请先核对商品状态"}
}

type xgjRateLimiter struct {
	mu       sync.Mutex
	next     time.Time
	interval time.Duration
}

// Shared across client instances, including lookup requests and worker writes.
var xgjSharedLimiter = &xgjRateLimiter{interval: xgjRequestInterval}

func (l *xgjRateLimiter) wait(ctx context.Context) error {
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		l.mu.Lock()
		now := time.Now()
		delay := l.next.Sub(now)
		if delay <= 0 {
			l.next = now.Add(l.interval)
			l.mu.Unlock()
			return nil
		}
		l.mu.Unlock()
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

type xgjClient struct {
	credentials XGJCredentials
	client      *http.Client
	baseURL     string
	now         func() time.Time
	limiter     *xgjRateLimiter
}

func newXGJClient(credentials XGJCredentials) *xgjClient {
	return &xgjClient{
		credentials: credentials,
		client: &http.Client{Timeout: xgjRequestTimeout, CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		}},
		baseURL: xgjAPIOrigin,
		now:     time.Now,
		limiter: xgjSharedLimiter,
	}
}

func xgjKnownPath(path string) bool {
	switch path {
	case xgjShopsPath, xgjAddressesPath, xgjCategoriesPath, xgjPropertiesPath,
		xgjProductsPath, xgjProductPath, xgjCreatePath, xgjPublishPath:
		return true
	}
	return false
}

func xgjSign(credentials XGJCredentials, body []byte, timestamp int64) string {
	bodyDigest := md5.Sum(body)
	plain := credentials.AppKey + "," + hex.EncodeToString(bodyDigest[:]) + "," + strconv.FormatInt(timestamp, 10) + "," + credentials.AppSecret
	digest := md5.Sum([]byte(plain))
	return hex.EncodeToString(digest[:])
}

func xgjJSON(payload any) ([]byte, error) {
	if payload == nil {
		payload = struct{}{}
	}
	// Durable JSON journals may escape HTML characters inside RawMessage.
	// Normalize before signing so persisted Chinese text and links use the
	// same UTF-8 wire representation as newly built requests. UseNumber keeps
	// product identifiers above JavaScript's exact integer range intact.
	if raw, ok := payload.(json.RawMessage); ok {
		if len(raw) > xgjRequestLimit || !json.Valid(raw) {
			return nil, xgjLocalError("invalid_request", "闲管家请求参数格式无效或过大")
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		if err := decoder.Decode(&payload); err != nil {
			return nil, xgjLocalError("invalid_request", "闲管家请求参数无法编码")
		}
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(payload); err != nil {
		return nil, xgjLocalError("invalid_request", "闲管家请求参数无法编码")
	}
	body := bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
	if len(body) > xgjRequestLimit || len(body) < 2 || body[0] != '{' || !json.Valid(body) {
		return nil, xgjLocalError("invalid_request", "闲管家请求参数格式无效或过大")
	}
	return body, nil
}

// call makes exactly one POST, including for read-only endpoints. It neither
// follows redirects nor retries errors, since create has no idempotency key.
func (c *xgjClient) call(ctx context.Context, path string, payload any, result any) error {
	if c == nil || !validXGJCredentials(c.credentials) {
		return xgjLocalError("credentials", "请填写完整有效的闲管家 AppKey 和 AppSecret")
	}
	if c.baseURL != xgjAPIOrigin || !xgjKnownPath(path) {
		return xgjLocalError("invalid_endpoint", "闲管家请求地址无效")
	}
	body, err := xgjJSON(payload)
	if err != nil {
		return err
	}
	requestCtx, cancel := context.WithTimeout(ctx, xgjRequestTimeout)
	defer cancel()
	limiter := c.limiter
	if limiter == nil {
		limiter = xgjSharedLimiter
	}
	if err := limiter.wait(requestCtx); err != nil {
		return &xgjError{Kind: "cancelled", Message: "闲管家请求在发送前已取消", cause: err}
	}
	if err := requestCtx.Err(); err != nil {
		return &xgjError{Kind: "cancelled", Message: "闲管家请求在发送前已取消", cause: err}
	}
	now := time.Now
	if c.now != nil {
		now = c.now
	}
	timestamp := now().Unix()
	query := url.Values{"appid": {c.credentials.AppKey}, "timestamp": {strconv.FormatInt(timestamp, 10)}, "sign": {xgjSign(c.credentials, body, timestamp)}}
	request, err := http.NewRequestWithContext(requestCtx, http.MethodPost, xgjAPIOrigin+path+"?"+query.Encode(), bytes.NewReader(body))
	if err != nil {
		return xgjLocalError("invalid_request", "闲管家请求参数无效")
	}
	// Disallow body replay even if a transport is reused after a broken connection.
	request.GetBody = nil
	request.Header.Set("Content-Type", "application/json;charset=utf-8")
	request.Header.Set("Accept", "application/json")
	request.Header.Set("User-Agent", "PortShelf")
	client := http.Client{}
	if c.client != nil {
		client = *c.client
	}
	client.Timeout = xgjRequestTimeout
	client.Jar = nil
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		// net/url.Error includes the signed URL, so never wrap the original error.
		failure := &xgjError{Kind: "transport", Ambiguous: true, Message: "闲管家请求结果未确认，请先核对商品状态"}
		if errors.Is(err, context.Canceled) {
			failure.Kind, failure.cause = "cancelled", context.Canceled
		} else if errors.Is(err, context.DeadlineExceeded) {
			failure.Kind, failure.cause = "timeout", context.DeadlineExceeded
		}
		return failure
	}
	defer response.Body.Close()
	if response.StatusCode >= 300 && response.StatusCode < 400 {
		return &xgjError{Kind: "redirect", Ambiguous: true, Message: "闲管家返回了重定向，已停止请求并保留待核对状态"}
	}
	responseBody, err := io.ReadAll(io.LimitReader(response.Body, xgjResponseLimit+1))
	if err != nil || len(responseBody) > xgjResponseLimit {
		return xgjInvalidResponse()
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return xgjHTTPError(response.StatusCode)
	}
	envelope, err := xgjObject(responseBody)
	if err != nil {
		return xgjInvalidResponse()
	}
	code, ok := xgjInteger(envelope["code"])
	if !ok {
		return xgjInvalidResponse()
	}
	if code != 0 {
		var message string
		_ = json.Unmarshal(envelope["msg"], &message)
		return xgjRejection(code, message)
	}
	data, err := xgjObject(envelope["data"])
	if err != nil || !xgjValidData(path, data) {
		return xgjInvalidResponse()
	}
	if result != nil {
		decoder := json.NewDecoder(bytes.NewReader(envelope["data"]))
		decoder.UseNumber()
		if err := decoder.Decode(result); err != nil {
			return xgjInvalidResponse()
		}
	}
	return nil
}

func xgjHTTPError(status int) error {
	if status == http.StatusUnauthorized || status == http.StatusForbidden {
		return &xgjError{Kind: "unauthorized", Code: int64(status), Message: "闲管家应用或店铺未授权，请检查应用状态、密钥及店铺授权"}
	}
	if status == http.StatusTooManyRequests {
		return &xgjError{Kind: "rate_limited", Code: int64(status), Message: "闲管家请求过于频繁，请稍后再试"}
	}
	// A gateway status alone cannot prove that a write was not applied upstream.
	return &xgjError{Kind: "http", Code: int64(status), Ambiguous: true, Message: "闲管家服务响应异常，请先核对商品状态"}
}

func xgjRejection(code int64, message string) error {
	failure := &xgjError{Kind: "rejected", Code: code, Message: "闲管家拒绝了本次请求，请检查应用和商品配置"}
	message = strings.ToLower(message)
	switch {
	case strings.Contains(message, "应用") && (strings.Contains(message, "下线") || strings.Contains(message, "禁用") || strings.Contains(message, "停用")):
		failure.Kind, failure.Message = "application_unavailable", "闲管家应用未上线或已停用，请在开放平台检查应用状态"
	case code == 401 || code == 403 || strings.Contains(message, "未授权") || strings.Contains(message, "授权过期") || strings.Contains(message, "签名"):
		failure.Kind, failure.Message = "unauthorized", "闲管家应用或店铺未授权，请检查应用状态、密钥及店铺授权"
	case code == 429 || strings.Contains(message, "频繁") || strings.Contains(message, "限流"):
		failure.Kind, failure.Message = "rate_limited", "闲管家请求过于频繁，请稍后再试"
	case code >= 500 && code < 600 || strings.Contains(message, "internal server error") || strings.Contains(message, "超时") || strings.Contains(message, "系统异常") || strings.Contains(message, "服务异常"):
		failure.Kind, failure.Ambiguous, failure.Message = "server", true, "闲管家服务响应异常，请先核对商品状态"
	}
	return failure
}

// Read a single JSON object, rejecting duplicate envelope/data fields and any
// trailing JSON. Missing code must never silently become success code zero.
func xgjObject(data []byte) (map[string]json.RawMessage, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	token, err := decoder.Token()
	if err != nil || token != json.Delim('{') {
		return nil, errors.New("expected object")
	}
	object := make(map[string]json.RawMessage)
	for decoder.More() {
		token, err = decoder.Token()
		key, ok := token.(string)
		if err != nil || !ok {
			return nil, errors.New("invalid field")
		}
		if _, duplicate := object[key]; duplicate {
			return nil, errors.New("duplicate field")
		}
		var raw json.RawMessage
		if err := decoder.Decode(&raw); err != nil {
			return nil, err
		}
		object[key] = raw
	}
	if _, err := decoder.Token(); err != nil {
		return nil, err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return nil, errors.New("trailing JSON")
	}
	return object, nil
}

func xgjInteger(raw json.RawMessage) (int64, bool) {
	if len(raw) == 0 || raw[0] == '"' || bytes.Equal(raw, []byte("null")) {
		return 0, false
	}
	var value int64
	if json.Unmarshal(raw, &value) != nil {
		return 0, false
	}
	return value, true
}

func xgjValidData(path string, data map[string]json.RawMessage) bool {
	switch path {
	case xgjShopsPath, xgjAddressesPath, xgjCategoriesPath, xgjPropertiesPath, xgjProductsPath:
		var rows []json.RawMessage
		raw := bytes.TrimSpace(data["list"])
		if len(raw) == 0 || raw[0] != '[' || json.Unmarshal(raw, &rows) != nil {
			return false
		}
		for _, row := range rows {
			fields, err := xgjObject(row)
			if err != nil {
				return false
			}
			switch path {
			case xgjShopsPath:
				id, ok := xgjInteger(fields["authorize_id"])
				if !ok || id <= 0 || !xgjNonemptyString(fields["user_name"]) {
					return false
				}
			case xgjAddressesPath:
				id, ok := xgjInteger(fields["address_id"])
				if !ok || id <= 0 {
					return false
				}
			case xgjCategoriesPath:
				if !xgjNonemptyString(fields["channel_cat_id"]) {
					return false
				}
			case xgjPropertiesPath:
				if !xgjNonemptyString(fields["property_id"]) {
					return false
				}
			case xgjProductsPath:
				id, ok := xgjInteger(fields["product_id"])
				if !ok || id <= 0 {
					return false
				}
			}
		}
		if path == xgjProductsPath {
			count, countOK := xgjInteger(data["count"])
			page, pageOK := xgjInteger(data["page_no"])
			size, sizeOK := xgjInteger(data["page_size"])
			return countOK && count >= 0 && pageOK && page > 0 && sizeOK && size > 0 && size <= 100
		}
	case xgjCreatePath, xgjProductPath:
		id, idOK := xgjInteger(data["product_id"])
		status, statusOK := xgjInteger(data["product_status"])
		if !idOK || id <= 0 || !statusOK || status == 0 {
			return false
		}
		if path == xgjProductPath {
			_, statusOK = xgjInteger(data["publish_status"])
			var shops []json.RawMessage
			raw := bytes.TrimSpace(data["publish_shop"])
			if !statusOK || len(raw) == 0 || raw[0] != '[' || json.Unmarshal(raw, &shops) != nil {
				return false
			}
			for _, shop := range shops {
				fields, err := xgjObject(shop)
				if err != nil || !xgjNonemptyString(fields["user_name"]) {
					return false
				}
				if raw, present := fields["status"]; present {
					if _, ok := xgjInteger(raw); !ok {
						return false
					}
				}
				if raw, present := fields["item_id"]; present {
					if id, ok := xgjInteger(raw); !ok || id < 0 {
						return false
					}
				}
			}
		}
	}
	return true
}

func xgjNonemptyString(raw json.RawMessage) bool {
	var value string
	return json.Unmarshal(raw, &value) == nil && strings.TrimSpace(value) != ""
}

type XGJShop struct {
	AuthorizeID      int64  `json:"authorize_id"`
	AuthorizeExpires int64  `json:"authorize_expires"`
	UserName         string `json:"user_name"`
	UserNick         string `json:"user_nick"`
	ShopName         string `json:"shop_name"`
	IsPro            bool   `json:"is_pro"`
	IsDepositEnough  bool   `json:"is_deposit_enough"`
	IsValid          bool   `json:"is_valid"`
	ValidEndTime     int64  `json:"valid_end_time"`
	ItemBizTypes     string `json:"item_biz_types"`
}

type XGJAddress struct {
	AddressID int64  `json:"address_id"`
	Type      int    `json:"type"`
	Province  int    `json:"province"`
	City      int    `json:"city"`
	District  int    `json:"district"`
	Region    string `json:"region"`
	Address   string `json:"address"`
	IsDefault bool   `json:"is_def"`
}

type XGJCategory struct {
	SpBizType      int    `json:"sp_biz_type"`
	SpBizName      string `json:"sp_biz_name"`
	ChannelCatID   string `json:"channel_cat_id"`
	ChannelCatName string `json:"channel_cat_name"`
}

type XGJPropertyValue struct {
	ValueID       string `json:"value_id"`
	ValueName     string `json:"value_name"`
	SubPropertyID string `json:"sub_property_id,omitempty"`
}

type XGJProperty struct {
	PropertyID   string             `json:"property_id"`
	PropertyName string             `json:"property_name"`
	Required     int                `json:"required"`
	Items        []XGJPropertyValue `json:"items"`
}

type XGJChannelPV struct {
	PropertyID   string `json:"property_id"`
	PropertyName string `json:"property_name"`
	ValueID      string `json:"value_id"`
	ValueName    string `json:"value_name"`
}

type XGJPublishShop struct {
	UserName       string   `json:"user_name"`
	Province       int      `json:"province"`
	City           int      `json:"city"`
	District       int      `json:"district"`
	Title          string   `json:"title"`
	Content        string   `json:"content"`
	Images         []string `json:"images"`
	ExpressWay     int      `json:"express_way"`
	ServiceSupport string   `json:"service_support,omitempty"`
}

type XGJCreateRequest struct {
	ItemBizType  int              `json:"item_biz_type"`
	SpBizType    int              `json:"sp_biz_type"`
	ChannelCatID string           `json:"channel_cat_id"`
	ChannelPV    []XGJChannelPV   `json:"channel_pv,omitempty"`
	Price        int64            `json:"price"`
	ExpressFee   int64            `json:"express_fee"`
	Stock        int              `json:"stock"`
	OuterID      string           `json:"outer_id"`
	StuffStatus  int              `json:"stuff_status"`
	PublishShop  []XGJPublishShop `json:"publish_shop"`
}

type XGJCreatedProduct struct {
	ProductID     int64 `json:"product_id"`
	ProductStatus int   `json:"product_status"`
}

type XGJProductShop struct {
	UserName string `json:"user_name"`
	ItemID   int64  `json:"item_id"`
	// status denotes whether this shop's information is selected (1) or not
	// selected (2). It is not an asynchronous publication success code.
	Status *int `json:"status"`
}

type XGJProductDetail struct {
	ProductID     int64            `json:"product_id"`
	ProductStatus int              `json:"product_status"`
	PublishStatus *int             `json:"publish_status"`
	OuterID       string           `json:"outer_id"`
	Title         string           `json:"title"`
	PublishShop   []XGJProductShop `json:"publish_shop"`
}

type XGJProductSummary struct {
	ProductID     int64  `json:"product_id"`
	ProductStatus int    `json:"product_status"`
	OuterID       string `json:"outer_id"`
	Title         string `json:"title"`
	UpdateTime    int64  `json:"update_time"`
	CreateTime    int64  `json:"create_time"`
}

type XGJProductPage struct {
	List     []XGJProductSummary `json:"list"`
	Count    int64               `json:"count"`
	PageNo   int                 `json:"page_no"`
	PageSize int                 `json:"page_size"`
}

func (c *xgjClient) listShops(ctx context.Context) ([]XGJShop, error) {
	var response struct {
		List []XGJShop `json:"list"`
	}
	err := c.call(ctx, xgjShopsPath, nil, &response)
	return response.List, err
}

func (c *xgjClient) listAddresses(ctx context.Context, addressType int) ([]XGJAddress, error) {
	var response struct {
		List []XGJAddress `json:"list"`
	}
	err := c.call(ctx, xgjAddressesPath, map[string]int{"type": addressType}, &response)
	return response.List, err
}

func (c *xgjClient) listCategories(ctx context.Context, itemBizType, spBizType int) ([]XGJCategory, error) {
	var response struct {
		List []XGJCategory `json:"list"`
	}
	err := c.call(ctx, xgjCategoriesPath, map[string]int{"item_biz_type": itemBizType, "sp_biz_type": spBizType}, &response)
	return response.List, err
}

func (c *xgjClient) listProperties(ctx context.Context, itemBizType, spBizType int, categoryID, subPropertyID string) ([]XGJProperty, error) {
	var response struct {
		List []XGJProperty `json:"list"`
	}
	payload := struct {
		ItemBizType   int    `json:"item_biz_type"`
		SpBizType     int    `json:"sp_biz_type"`
		ChannelCatID  string `json:"channel_cat_id"`
		SubPropertyID string `json:"sub_property_id,omitempty"`
	}{itemBizType, spBizType, categoryID, subPropertyID}
	err := c.call(ctx, xgjPropertiesPath, payload, &response)
	return response.List, err
}

func (c *xgjClient) listProducts(ctx context.Context, pageNo, pageSize int, updateFrom, updateTo int64) (XGJProductPage, error) {
	var response XGJProductPage
	if pageNo < 1 || pageNo > 100 || pageSize < 1 || pageSize > 100 || updateFrom < 0 || updateTo < 0 || updateFrom > updateTo {
		return response, xgjLocalError("invalid_request", "闲管家商品查询范围无效")
	}
	payload := struct {
		PageNo     int     `json:"page_no"`
		PageSize   int     `json:"page_size"`
		UpdateTime []int64 `json:"update_time,omitempty"`
	}{PageNo: pageNo, PageSize: pageSize}
	if updateFrom != 0 || updateTo != 0 {
		payload.UpdateTime = []int64{updateFrom, updateTo}
	}
	err := c.call(ctx, xgjProductsPath, payload, &response)
	if err == nil && (response.PageNo != pageNo || response.PageSize != pageSize || len(response.List) > pageSize || response.Count < int64(len(response.List))) {
		err = xgjInvalidResponse()
	}
	return response, err
}

func (c *xgjClient) productDetail(ctx context.Context, productID int64) (XGJProductDetail, error) {
	var response XGJProductDetail
	if productID <= 0 {
		return response, xgjLocalError("invalid_request", "闲管家商品编号无效")
	}
	err := c.call(ctx, xgjProductPath, map[string]int64{"product_id": productID}, &response)
	if err == nil && response.ProductID != productID {
		err = xgjInvalidResponse()
	}
	return response, err
}

func (c *xgjClient) createProduct(ctx context.Context, payload XGJCreateRequest) (XGJCreatedProduct, error) {
	var response XGJCreatedProduct
	err := c.call(ctx, xgjCreatePath, payload, &response)
	return response, err
}

func (c *xgjClient) publishProduct(ctx context.Context, productID int64, userName string) error {
	if productID <= 0 || strings.TrimSpace(userName) == "" {
		return xgjLocalError("invalid_request", "请选择有效的闲管家商品和店铺")
	}
	payload := struct {
		ProductID int64    `json:"product_id"`
		UserName  []string `json:"user_name"`
	}{productID, []string{userName}}
	return c.call(ctx, xgjPublishPath, payload, nil)
}
