#include "esunny_v10_bridge.h"
#include "DstarTradeApi.h"

#include <algorithm>
#include <cstring>
#include <sstream>
#include <string>

namespace {

template <size_t N> void copy_text(char (&dest)[N], const char *src) {
    std::memset(dest, 0, N);
    if (src) std::strncpy(dest, src, N - 1);
}

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

class Bridge final : public IDstarTradeSpi {
public:
    Bridge(es_event_callback cb, void *user) : callback_(cb), user_(user), api_(CreateDstarTradeApi()) {}
    ~Bridge() { if (api_) { api_->RegisterSpi(nullptr); FreeDstarTradeApi(api_); } }

    int connect(const char *ip, unsigned short port, const char *account, const char *password,
                const char *app_id, const char *license_no, const char *log_path) {
        if (!api_) return -100;
        copy_text(login_.AccountNo, account); copy_text(login_.Password, password);
        copy_text(login_.AppId, app_id); copy_text(login_.LicenseNo, license_no);
        api_->RegisterSpi(this);
        api_->RegisterFrontAddress(const_cast<char *>(ip), port);
        api_->SetApiLogPath(const_cast<char *>(log_path));
        api_->SetLoginInfo(&login_);
        api_->SetCpuId(-1, -1);
        api_->SetSubscribeStartId(-1);

        char system_info[2048] = {0}; int length = sizeof(system_info); unsigned int version = 0;
        const int info_rc = api_->GetSystemInfo(system_info, &length, &version);
        if (info_rc != 0) return info_rc;
        DstarApiSubmitInfoField submit = {};
        copy_text(submit.AccountNo, account); copy_text(submit.ClientAppId, app_id);
        copy_text(submit.LicenseNo, license_no);
        submit.AuthType = DSTAR_API_AUTHTYPE_DIRECT; submit.AuthKeyVersion = version;
        std::memcpy(submit.SystemInfo, system_info,
                    std::min(static_cast<size_t>(length), sizeof(submit.SystemInfo)));
        api_->SetSubmitInfo(&submit);

        return api_->Init();
    }

    int insert(const char *contract, unsigned int contract_index, char side, char offset, char hedge,
               char order_type, char valid_type, unsigned int volume, unsigned int min_volume,
               double price, unsigned int request_id, long long reference, unsigned int seat_index) {
        if (!api_ || !ready_) return -1;
        DstarApiReqOrderInsertField req = {};
        req.Direct = side; req.Offset = offset; req.Hedge = hedge; req.OrderType = order_type;
        req.ValidType = valid_type; req.SeatIndex = seat_index; req.AccountIndex = account_index_;
        req.ContractIndex = contract_index; copy_text(req.ContractNo, contract);
        req.OrderQty = volume; req.MinQty = min_volume; req.OrderPrice = price;
        req.ClientReqId = request_id; req.Reference = reference;
        return api_->ReqOrderInsert(&req);
    }

    int cancel(unsigned long long order_id, const char *system_no, unsigned int request_id,
               long long reference, unsigned int seat_index) {
        if (!api_ || !ready_) return -1;
        DstarApiReqOrderDeleteField req = {};
        req.AccountIndex = account_index_; req.ClientReqId = request_id; req.Reference = reference;
        req.SeatIndex = seat_index; req.OrderId = order_id; copy_text(req.SystemNo, system_no);
        return api_->ReqOrderDelete(&req);
    }

    int funds() { return api_ ? api_->ReqQryFund() : -1; }
    int positions() { return api_ ? api_->ReqQryPosition() : -1; }

    void OnFrontDisconnected() override { ready_ = false; emit("gateway.disconnected", "{}"); }
    void OnRspError(DstarApiErrorCodeType code) override { emit_code("gateway.error", code); }
    void OnRspUserLogin(const DstarApiRspLoginField *p) override {
        if (!p) return; account_index_ = p->AccountIndex;
        std::ostringstream s; s << "{\"account\":" << quote(p->AccountNo)
            << ",\"trade_date\":" << quote(p->TradeDate) << ",\"error_code\":" << p->ErrorCode << "}";
        emit("gateway.login", s.str());
    }
    void OnApiReady(const DstarApiSerialIdType serial) override {
        ready_ = true; std::ostringstream s; s << "{\"serial_id\":" << serial << "}"; emit("gateway.ready", s.str());
    }
    void OnRspOrderInsert(const DstarApiRspOrderInsertField *p) override { emit_order_response(p); }
    void OnRspOrderDelete(const DstarApiRspOrderDeleteField *p) override { emit_order_response(p); }
    void OnRtnOrder(const DstarApiOrderField *p) override { emit_order(p); }
    void OnRspOrder(const DstarApiOrderField *p) override { emit_order(p); }
    void OnRtnMatch(const DstarApiMatchField *p) override { emit_trade(p); }
    void OnRspMatch(const DstarApiMatchField *p) override { emit_trade(p); }
    void OnRspQryFund(const DstarApiFundField *p) override { emit_fund(p); }
    void OnRspFund(const DstarApiFundField *p) override { emit_fund(p); }
    void OnRspQryPosition(const DstarApiPositionField *p, bool last) override {
        if (p) emit_position(p); if (last) emit("position.end", "{}");
    }
    void OnRspPosition(const DstarApiPositionField *p) override { emit_position(p); }

    void OnRspPwdMod(const DstarApiRspPwdModField*) override {}
    void OnRspSubmitInfo(const DstarApiRspSubmitInfoField*) override {}
    void OnRspContract(const DstarApiContractField *p) override {
        if (!p) return;
        std::ostringstream s;
        s << "{\"contract_index\":" << p->ContractIndex
          << ",\"contract\":" << quote(p->ContractNo) << "}";
        emit("contract", s.str());
    }
    void OnRspCmbContract(const DstarApiCmbContractField*) override {}
    void OnRspSeat(const DstarApiSeatField*) override {}
    void OnRspTrdFeeParam(const DstarApiTrdFeeParamField*) override {}
    void OnRspTrdMarParam(const DstarApiTrdMarParamField*) override {}
    void OnRspTradeRight(const DstarApiTradeRightField*) override {}
    void OnRspAccountCommList(const DstarApiAccountCommListField*) override {}
    void OnRspTrdExchangeState(const DstarApiTrdExchangeStateField*) override {}
    void OnRspPrePosition(const DstarApiPrePositionField*) override {}
    void OnRspOffer(const DstarApiOfferField*) override {}
    void OnRspCashInOut(const DstarApiCashInOutField*) override {}
    void OnRspUdpAuth(const DstarApiRspUdpAuthField*) override {}
    void OnRspOfferInsert(const DstarApiRspOfferInsertField*) override {}
    void OnRspLastReqId(const DstaApiRspLastReqIdField*) override {}
    void OnRtnPwdMod(const DstarApiPwdModField*) override {}
    void OnRtnCashInOut(const DstarApiCashInOutField*) override {}
    void OnRtnOffer(const DstarApiOfferField*) override {}
    void OnRtnEnquiry(const DstarApiEnquiryField*) override {}
    void OnRtnTrdExchangeState(const DstarApiTrdExchangeStateField*) override {}
    void OnRtnPosiProfit(const DstarApiPosiProfitField*) override {}
    void OnRtnSeat(const DstarApiSeatField*) override {}
    void OnRtnTradeRight(const DstarApiTradeRightField*) override {}
    void OnRtnTradeRightDel(const DstarApiTradeRightDelField*) override {}

private:
    void emit(const char *type, const std::string &json) { if (callback_) callback_(type, json.c_str(), user_); }
    void emit_code(const char *type, unsigned int code) {
        std::ostringstream s; s << "{\"error_code\":" << code << "}"; emit(type, s.str());
    }
    void emit_order_response(const DstarApiRspOrderInsertField *p) {
        if (!p) return; std::ostringstream s;
        s << "{\"request_id\":" << p->ClientReqId << ",\"order_id\":" << p->OrderId
          << ",\"error_code\":" << p->ErrCode << ",\"status\":\""
          << (p->ErrCode ? "rejected" : "accepted") << "\"}"; emit("order", s.str());
    }
    void emit_order(const DstarApiOrderField *p) {
        if (!p) return; const char *status = p->ErrCode ? "rejected" :
            (p->OrderQty > 0 && p->MatchQty >= p->OrderQty ? "filled" :
             (p->MatchQty > 0 ? "partially_filled" : "accepted"));
        std::ostringstream s; s << "{\"request_id\":" << p->Reference << ",\"order_id\":" << p->OrderId
          << ",\"system_no\":" << quote(p->SystemNo) << ",\"contract\":" << quote(p->ContractNo1)
          << ",\"traded_volume\":" << p->MatchQty << ",\"error_code\":" << p->ErrCode
          << ",\"raw_state\":\"" << p->OrderState << "\",\"status\":\"" << status << "\"}";
        emit("order", s.str());
    }
    void emit_trade(const DstarApiMatchField *p) {
        if (!p) return; std::ostringstream s; s << "{\"trade_id\":\"" << p->MatchId
          << "\",\"order_id\":" << p->OrderId << ",\"contract\":" << quote(p->ContractNo)
          << ",\"side\":\"" << p->Direct << "\",\"offset\":\"" << p->Offset
          << "\",\"volume\":" << p->MatchQty << ",\"price\":" << p->MatchPrice
          << ",\"fee\":" << p->Fee << "}"; emit("trade", s.str());
    }
    void emit_fund(const DstarApiFundField *p) {
        if (!p) return; std::ostringstream s; s << "{\"account\":" << quote(p->AccountNo)
          << ",\"equity\":" << p->Equity << ",\"available\":" << p->Avail
          << ",\"margin\":" << p->Margin << ",\"fee\":" << p->Fee << "}"; emit("fund", s.str());
    }
    void emit_position(const DstarApiPositionField *p) {
        if (!p) return; std::ostringstream s; s << "{\"account\":" << quote(p->AccountNo)
          << ",\"contract\":" << quote(p->ContractNo) << ",\"long_yesterday\":" << p->PreBuyQty
          << ",\"long_today\":" << p->TodayBuyQty << ",\"short_yesterday\":" << p->PreSellQty
          << ",\"short_today\":" << p->TodaySellQty << ",\"long_avg_price\":" << p->BuyAvgPrice
          << ",\"short_avg_price\":" << p->SellAvgPrice << "}"; emit("position", s.str());
    }

    es_event_callback callback_ = nullptr; void *user_ = nullptr; IDstarTradeApi *api_ = nullptr;
    DstarApiReqLoginField login_ = {}; DstarApiAccountIndexType account_index_ = 0; bool ready_ = false;
};

Bridge *as_bridge(void *handle) { return static_cast<Bridge *>(handle); }
}

extern "C" {
void *es_create(es_event_callback cb, void *user) { try { return new Bridge(cb, user); } catch (...) { return nullptr; } }
void es_destroy(void *h) { delete as_bridge(h); }
int es_connect(void *h, const char *ip, const char *account, const char *password, const char *app_id,
               const char *license, const char *log_path, unsigned short port) {
    return h ? as_bridge(h)->connect(ip, port, account, password, app_id, license, log_path) : -100;
}
int es_insert_order(void *h, const char *contract, unsigned int index, char side, char offset, char hedge,
                    char type, char valid, unsigned int volume, unsigned int min_volume, double price,
                    unsigned int req, long long ref, unsigned int seat) {
    return h ? as_bridge(h)->insert(contract, index, side, offset, hedge, type, valid, volume, min_volume, price, req, ref, seat) : -100;
}
int es_cancel_order(void *h, unsigned long long order_id, const char *system_no, unsigned int req,
                    long long ref, unsigned int seat) {
    return h ? as_bridge(h)->cancel(order_id, system_no, req, ref, seat) : -100;
}
int es_query_funds(void *h) { return h ? as_bridge(h)->funds() : -100; }
int es_query_positions(void *h) { return h ? as_bridge(h)->positions() : -100; }
}
