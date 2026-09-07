#include "esunny_v10_quote_bridge.h"
#include "DstarQuoteApi.h"

#include <sstream>
#include <string>

namespace {

std::string quote(const char *value) {
    std::string out = "\"";
    if (value) {
        for (const unsigned char c : std::string(value)) {
            if (c == '\\' || c == '"') { out += '\\'; out += static_cast<char>(c); }
            else if (c >= 0x20) out += static_cast<char>(c);
        }
    }
    return out + "\"";
}

class QuoteBridge final : public DstarQuoteSpi {
public:
    QuoteBridge(esq_event_callback callback, void *user_data)
        : callback_(callback), user_data_(user_data), api_(CreateDstarQuoteApi()) {}

    ~QuoteBridge() {
        if (api_) {
            api_->SetSpi(nullptr);
            FreeDstarQuoteApi(api_);
        }
    }

    int connect(const char *ip, unsigned short port, const char *log_path) {
        if (!api_) return -100;
        int rc = api_->SetSpi(this);
        if (rc != 0) return rc;
        if (!api_->SetHostAddress(ip, port)) return -101;
        api_->SetApiLogPath(const_cast<char *>(log_path));
        api_->SetCpuId(-1);
        api_->SetAutoRelogin(true);
        return api_->Start();
    }

    int subscribe(const char *contract) { return api_ && ready_ ? api_->Subscribe(contract) : -1; }
    int unsubscribe(const char *contract) { return api_ && ready_ ? api_->UnSubscribe(contract) : -1; }
    int query_contracts() { return api_ && ready_ ? api_->QryContract() : -1; }

    void OnApiReady() override {
        ready_ = true;
        emit("quote.ready", "{}");
    }

    void OnDisconnect(int reason_code) override {
        ready_ = false;
        std::ostringstream json;
        json << "{\"reason_code\":" << reason_code << "}";
        emit("quote.disconnected", json.str());
    }

    void OnError(int error_code) override {
        std::ostringstream json;
        json << "{\"error_code\":" << error_code << "}";
        emit("quote.error", json.str());
    }

    void OnRspCommodity(const DstarQuoteApiCommodityData *data, bool is_last) override {
        if (!data) return;
        std::ostringstream json;
        json << "{\"commodity\":" << quote(data->CommodityNo)
             << ",\"exchange\":" << quote(data->ExchangeNo)
             << ",\"commodity_type\":\"" << data->CommodityType
             << "\",\"contract_size\":" << data->ContractSize
             << ",\"tick_size\":" << data->ContractTickSize
             << ",\"is_last\":" << (is_last ? "true" : "false") << "}";
        emit("quote.commodity", json.str());
    }

    void OnRspContract(const char *contract, bool is_last) override {
        std::ostringstream json;
        json << "{\"contract\":" << quote(contract)
             << ",\"is_last\":" << (is_last ? "true" : "false") << "}";
        emit("quote.contract", json.str());
    }

    void OnRtnQuote(const DstarApiQuoteData *q) override {
        if (!q) return;
        std::ostringstream json;
        json.precision(15);
        json << "{\"contract\":" << quote(q->QContractNo)
             << ",\"timestamp\":" << q->QDateTimeStamp
             << ",\"last_price\":" << q->QLastPrice
             << ",\"last_volume\":" << q->QLastQty
             << ",\"bid_price\":" << q->QBidPrice1
             << ",\"bid_volume\":" << q->QBidQty1
             << ",\"ask_price\":" << q->QAskPrice1
             << ",\"ask_volume\":" << q->QAskQty1
             << ",\"open_price\":" << q->QOpeningPrice
             << ",\"high_price\":" << q->QHighPrice
             << ",\"low_price\":" << q->QLowPrice
             << ",\"pre_settlement\":" << q->QPreSettlePrice
             << ",\"upper_limit\":" << q->QLimitUpPrice
             << ",\"lower_limit\":" << q->QLimitDownPrice
             << ",\"total_volume\":" << q->QTotalQty
             << ",\"open_interest\":" << q->QPositionQty << "}";
        emit("tick", json.str());
    }

private:
    void emit(const char *type, const std::string &payload) {
        if (callback_) callback_(type, payload.c_str(), user_data_);
    }

    esq_event_callback callback_ = nullptr;
    void *user_data_ = nullptr;
    DstarQuoteApi *api_ = nullptr;
    bool ready_ = false;
};

QuoteBridge *bridge(void *handle) { return static_cast<QuoteBridge *>(handle); }
}

extern "C" {
void *esq_create(esq_event_callback callback, void *user_data) {
    try { return new QuoteBridge(callback, user_data); } catch (...) { return nullptr; }
}
void esq_destroy(void *handle) { delete bridge(handle); }
int esq_connect(void *handle, const char *ip, unsigned short port, const char *log_path) {
    return handle ? bridge(handle)->connect(ip, port, log_path) : -100;
}
int esq_subscribe(void *handle, const char *contract) {
    return handle ? bridge(handle)->subscribe(contract) : -100;
}
int esq_unsubscribe(void *handle, const char *contract) {
    return handle ? bridge(handle)->unsubscribe(contract) : -100;
}
int esq_query_contracts(void *handle) {
    return handle ? bridge(handle)->query_contracts() : -100;
}
}

