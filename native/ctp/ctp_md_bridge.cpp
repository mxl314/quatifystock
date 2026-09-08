#include "ThostFtdcMdApi.h"

#include <cmath>
#include <cstring>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>

#ifdef _WIN32
#define CTP_EXPORT extern "C" __declspec(dllexport)
#define CTP_CALL __cdecl
#else
#define CTP_EXPORT extern "C"
#define CTP_CALL
#endif

typedef void(CTP_CALL* ctp_event_callback)(const char*, const char*, void*);

namespace {
std::string esc(const char* value) {
    std::ostringstream out;
    for (const unsigned char c : std::string(value ? value : "")) {
        switch (c) {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (c < 0x20) out << "?";
            else out << static_cast<char>(c);
        }
    }
    return out.str();
}

double price(double value) {
    return std::isfinite(value) && std::fabs(value) < 1e100 ? value : 0.0;
}

class MdBridge final : public CThostFtdcMdSpi {
public:
    MdBridge(ctp_event_callback callback, void* user) : callback_(callback), user_(user) {}
    ~MdBridge() { close(); }

    int connect(const char* front, const char* broker, const char* user, const char* password,
                const char* flow_path) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (api_) return -2;
        broker_ = broker ? broker : "";
        user_id_ = user ? user : "";
        password_ = password ? password : "";
        api_ = CThostFtdcMdApi::CreateFtdcMdApi(flow_path ? flow_path : "", false, false, true);
        if (!api_) return -3;
        api_->RegisterSpi(this);
        api_->RegisterFront(const_cast<char*>(front));
        api_->Init();
        return 0;
    }

    void close() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (api_) {
            api_->RegisterSpi(nullptr);
            api_->Release();
            api_ = nullptr;
        }
    }

    int subscribe(const char* instrument, bool enabled) {
        if (!api_ || !instrument || !*instrument) return -1;
        char* instruments[] = {const_cast<char*>(instrument)};
        return enabled ? api_->SubscribeMarketData(instruments, 1)
                       : api_->UnSubscribeMarketData(instruments, 1);
    }

    void OnFrontConnected() override {
        emit("ctp.md.connected", "{}");
        CThostFtdcReqUserLoginField req{};
        copy(req.BrokerID, broker_);
        copy(req.UserID, user_id_);
        copy(req.Password, password_);
        const int rc = api_->ReqUserLogin(&req, ++request_id_);
        if (rc != 0) emit_error("md.login.request", rc, "ReqUserLogin rejected locally");
    }

    void OnFrontDisconnected(int reason) override {
        std::ostringstream out; out << "{\"reason\":" << reason << "}";
        emit("ctp.md.disconnected", out.str());
    }

    void OnRspUserLogin(CThostFtdcRspUserLoginField* login, CThostFtdcRspInfoField* info,
                        int request_id, bool last) override {
        if (failed(info)) { emit_rsp_error("md.login", info, request_id); return; }
        std::ostringstream out;
        out << "{\"request_id\":" << request_id
            << ",\"trading_day\":\"" << esc(login ? login->TradingDay : "") << "\""
            << ",\"last\":" << (last ? "true" : "false") << "}";
        emit("gateway.login", out.str());
        emit("gateway.ready", "{\"gateway\":\"ctp.md\"}");
    }

    void OnRspError(CThostFtdcRspInfoField* info, int request_id, bool) override {
        emit_rsp_error("md.response", info, request_id);
    }

    void OnRtnDepthMarketData(CThostFtdcDepthMarketDataField* d) override {
        if (!d) return;
        const char* day = d->ActionDay[0] ? d->ActionDay : d->TradingDay;
        std::string ds = day ? day : "";
        if (ds.size() == 8) ds = ds.substr(0,4) + "-" + ds.substr(4,2) + "-" + ds.substr(6,2);
        std::ostringstream ts;
        ts << ds << " " << d->UpdateTime << "." << std::setw(3) << std::setfill('0') << d->UpdateMillisec;
        std::ostringstream out;
        out << std::setprecision(15)
            << "{\"instrument\":\"" << esc(d->InstrumentID) << "\""
            << ",\"exchange\":\"" << esc(d->ExchangeID) << "\""
            << ",\"timestamp\":\"" << esc(ts.str().c_str()) << "\""
            << ",\"last_price\":" << price(d->LastPrice)
            << ",\"bid_price\":" << price(d->BidPrice1)
            << ",\"bid_volume\":" << d->BidVolume1
            << ",\"ask_price\":" << price(d->AskPrice1)
            << ",\"ask_volume\":" << d->AskVolume1
            << ",\"open_price\":" << price(d->OpenPrice)
            << ",\"high_price\":" << price(d->HighestPrice)
            << ",\"low_price\":" << price(d->LowestPrice)
            << ",\"pre_settlement\":" << price(d->PreSettlementPrice)
            << ",\"upper_limit\":" << price(d->UpperLimitPrice)
            << ",\"lower_limit\":" << price(d->LowerLimitPrice)
            << ",\"total_volume\":" << d->Volume
            << ",\"open_interest\":" << static_cast<long long>(d->OpenInterest) << "}";
        emit("tick", out.str());
    }

private:
    template <size_t N> static void copy(char (&target)[N], const std::string& value) {
        std::strncpy(target, value.c_str(), N - 1); target[N - 1] = '\0';
    }
    static bool failed(CThostFtdcRspInfoField* info) { return info && info->ErrorID != 0; }
    void emit(const char* type, const std::string& payload) {
        if (callback_) callback_(type, payload.c_str(), user_);
    }
    void emit_error(const char* where, int code, const char* message) {
        std::ostringstream out;
        out << "{\"where\":\"" << where << "\",\"error_code\":" << code
            << ",\"message\":\"" << esc(message) << "\"}";
        emit("gateway.error", out.str());
    }
    void emit_rsp_error(const char* where, CThostFtdcRspInfoField* info, int request_id) {
        std::ostringstream out;
        out << "{\"where\":\"" << where << "\",\"request_id\":" << request_id
            << ",\"error_code\":" << (info ? info->ErrorID : -1)
            << ",\"message\":\"" << esc(info ? info->ErrorMsg : "unknown CTP error") << "\"}";
        emit("gateway.error", out.str());
    }

    ctp_event_callback callback_{};
    void* user_{};
    CThostFtdcMdApi* api_{};
    std::string broker_, user_id_, password_;
    int request_id_{};
    std::mutex mutex_;
};
}

CTP_EXPORT void* CTP_CALL ctp_md_create(ctp_event_callback callback, void* user) {
    try { return new MdBridge(callback, user); } catch (...) { return nullptr; }
}
CTP_EXPORT void CTP_CALL ctp_md_destroy(void* handle) { delete static_cast<MdBridge*>(handle); }
CTP_EXPORT int CTP_CALL ctp_md_connect(void* handle, const char* front, const char* broker,
                                       const char* user, const char* password, const char* flow) {
    return handle ? static_cast<MdBridge*>(handle)->connect(front, broker, user, password, flow) : -1;
}
CTP_EXPORT int CTP_CALL ctp_md_subscribe(void* handle, const char* instrument) {
    return handle ? static_cast<MdBridge*>(handle)->subscribe(instrument, true) : -1;
}
CTP_EXPORT int CTP_CALL ctp_md_unsubscribe(void* handle, const char* instrument) {
    return handle ? static_cast<MdBridge*>(handle)->subscribe(instrument, false) : -1;
}
