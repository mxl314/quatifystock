#include "ThostFtdcTraderApi.h"

#include <cstdlib>
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
        if (c == '\\') out << "\\\\"; else if (c == '"') out << "\\\"";
        else if (c == '\n') out << "\\n"; else if (c == '\r') out << "\\r";
        else if (c < 0x20) out << "?"; else out << static_cast<char>(c);
    }
    return out.str();
}

class TdBridge final : public CThostFtdcTraderSpi {
public:
    TdBridge(ctp_event_callback callback, void* user) : callback_(callback), user_(user) {}
    ~TdBridge() { close(); }

    int connect(const char* front, const char* broker, const char* user, const char* password,
                const char* app_id, const char* auth_code, const char* flow_path) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (api_) return -2;
        broker_ = broker ? broker : ""; user_id_ = user ? user : "";
        password_ = password ? password : ""; app_id_ = app_id ? app_id : "";
        auth_code_ = auth_code ? auth_code : "";
        api_ = CThostFtdcTraderApi::CreateFtdcTraderApi(flow_path ? flow_path : "", true);
        if (!api_) return -3;
        api_->RegisterSpi(this);
        api_->SubscribePrivateTopic(THOST_TERT_QUICK);
        api_->SubscribePublicTopic(THOST_TERT_QUICK);
        api_->RegisterFront(const_cast<char*>(front));
        api_->Init();
        return 0;
    }

    void close() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (api_) { api_->RegisterSpi(nullptr); api_->Release(); api_ = nullptr; }
    }

    int insert(const char* instrument, const char* exchange, char side, char offset, char hedge,
               char order_type, char time_in_force, int volume, int min_volume, double price,
               int request_id, int order_ref) {
        if (!api_ || !ready_) return -10;
        CThostFtdcInputOrderField req{};
        copy(req.BrokerID, broker_); copy(req.InvestorID, user_id_); copy(req.UserID, user_id_);
        copy(req.InstrumentID, instrument ? instrument : ""); copy(req.ExchangeID, exchange ? exchange : "");
        copy(req.OrderRef, std::to_string(order_ref));
        req.Direction = side == 'B' ? THOST_FTDC_D_Buy : THOST_FTDC_D_Sell;
        req.CombOffsetFlag[0] = offset == 'O' ? THOST_FTDC_OF_Open :
            (offset == 'T' ? THOST_FTDC_OF_CloseToday : THOST_FTDC_OF_Close);
        req.CombHedgeFlag[0] = hedge == 'B' ? THOST_FTDC_HF_Hedge : THOST_FTDC_HF_Speculation;
        req.OrderPriceType = order_type == '1' ? THOST_FTDC_OPT_AnyPrice : THOST_FTDC_OPT_LimitPrice;
        req.LimitPrice = price; req.VolumeTotalOriginal = volume;
        req.TimeCondition = time_in_force == '3' ? THOST_FTDC_TC_GFD : THOST_FTDC_TC_IOC;
        req.VolumeCondition = time_in_force == '1' ? THOST_FTDC_VC_CV : THOST_FTDC_VC_AV;
        req.MinVolume = min_volume > 0 ? min_volume : 1;
        req.ContingentCondition = THOST_FTDC_CC_Immediately;
        req.ForceCloseReason = THOST_FTDC_FCC_NotForceClose;
        return api_->ReqOrderInsert(&req, request_id);
    }

    int cancel(const char* instrument, const char* exchange, const char* order_ref,
               int front_id, int session_id, const char* system_no, int request_id) {
        if (!api_ || !ready_) return -10;
        CThostFtdcInputOrderActionField req{};
        copy(req.BrokerID, broker_); copy(req.InvestorID, user_id_); copy(req.UserID, user_id_);
        copy(req.InstrumentID, instrument ? instrument : ""); copy(req.ExchangeID, exchange ? exchange : "");
        copy(req.OrderRef, order_ref ? order_ref : ""); copy(req.OrderSysID, system_no ? system_no : "");
        req.FrontID = front_id; req.SessionID = session_id; req.ActionFlag = THOST_FTDC_AF_Delete;
        return api_->ReqOrderAction(&req, request_id);
    }

    int query_funds() {
        if (!api_ || !ready_) return -10;
        CThostFtdcQryTradingAccountField req{}; copy(req.BrokerID, broker_); copy(req.InvestorID, user_id_);
        return api_->ReqQryTradingAccount(&req, ++request_id_);
    }
    int query_positions() {
        if (!api_ || !ready_) return -10;
        CThostFtdcQryInvestorPositionField req{}; copy(req.BrokerID, broker_); copy(req.InvestorID, user_id_);
        return api_->ReqQryInvestorPosition(&req, ++request_id_);
    }
    int query_contracts() {
        if (!api_ || !ready_) return -10;
        CThostFtdcQryInstrumentField req{};
        return api_->ReqQryInstrument(&req, ++request_id_);
    }

    void OnFrontConnected() override {
        emit("ctp.td.connected", "{}");
        if (!app_id_.empty() || !auth_code_.empty()) authenticate(); else login();
    }
    void OnFrontDisconnected(int reason) override {
        ready_ = false; std::ostringstream out; out << "{\"reason\":" << reason << "}";
        emit("ctp.td.disconnected", out.str());
    }
    void OnRspAuthenticate(CThostFtdcRspAuthenticateField*, CThostFtdcRspInfoField* info,
                           int request_id, bool) override {
        if (failed(info)) { emit_error("td.authenticate", info, request_id); return; }
        login();
    }
    void OnRspUserLogin(CThostFtdcRspUserLoginField* login_rsp, CThostFtdcRspInfoField* info,
                        int request_id, bool) override {
        if (failed(info)) { emit_error("td.login", info, request_id); return; }
        if (login_rsp) { front_id_ = login_rsp->FrontID; session_id_ = login_rsp->SessionID; }
        std::ostringstream out; out << "{\"request_id\":" << request_id << ",\"front_id\":" << front_id_
            << ",\"session_id\":" << session_id_ << ",\"trading_day\":\""
            << esc(login_rsp ? login_rsp->TradingDay : "") << "\"}";
        emit("gateway.login", out.str());
        CThostFtdcSettlementInfoConfirmField req{};
        copy(req.BrokerID, broker_); copy(req.InvestorID, user_id_);
        const int rc = api_->ReqSettlementInfoConfirm(&req, ++request_id_);
        if (rc != 0) emit_local_error("td.settlement_confirm", rc);
    }
    void OnRspSettlementInfoConfirm(CThostFtdcSettlementInfoConfirmField*, CThostFtdcRspInfoField* info,
                                    int request_id, bool) override {
        if (failed(info)) { emit_error("td.settlement_confirm", info, request_id); return; }
        ready_ = true; emit("gateway.ready", "{\"gateway\":\"ctp.td\"}");
    }
    void OnRspOrderInsert(CThostFtdcInputOrderField* order, CThostFtdcRspInfoField* info,
                          int request_id, bool) override {
        if (failed(info)) emit_order_error("td.order_insert", order ? order->OrderRef : "", info, request_id);
    }
    void OnErrRtnOrderInsert(CThostFtdcInputOrderField* order, CThostFtdcRspInfoField* info) override {
        emit_order_error("td.order_insert", order ? order->OrderRef : "", info, order ? order->RequestID : 0);
    }
    void OnRspOrderAction(CThostFtdcInputOrderActionField*, CThostFtdcRspInfoField* info,
                          int request_id, bool) override {
        if (failed(info)) emit_error("td.order_action", info, request_id);
    }
    void OnErrRtnOrderAction(CThostFtdcOrderActionField*, CThostFtdcRspInfoField* info) override {
        emit_error("td.order_action", info, 0);
    }
    void OnRtnOrder(CThostFtdcOrderField* o) override {
        if (!o) return;
        const char* status = "unknown";
        if (o->OrderStatus == THOST_FTDC_OST_AllTraded) status = "filled";
        else if (o->OrderStatus == THOST_FTDC_OST_PartTradedQueueing || o->OrderStatus == THOST_FTDC_OST_PartTradedNotQueueing) status = "partially_filled";
        else if (o->OrderStatus == THOST_FTDC_OST_NoTradeQueueing) status = "accepted";
        else if (o->OrderStatus == THOST_FTDC_OST_Canceled) status = "cancelled";
        std::ostringstream out; out << std::setprecision(15)
            << "{\"order_id\":" << std::atoll(o->OrderRef) << ",\"request_id\":" << o->RequestID
            << ",\"order_ref\":\"" << esc(o->OrderRef) << "\",\"system_no\":\"" << esc(o->OrderSysID)
            << "\",\"instrument\":\"" << esc(o->InstrumentID) << "\",\"exchange\":\"" << esc(o->ExchangeID)
            << "\",\"status\":\"" << status << "\",\"traded_volume\":" << o->VolumeTraded
            << ",\"total_volume\":" << o->VolumeTotalOriginal << ",\"front_id\":" << o->FrontID
            << ",\"session_id\":" << o->SessionID << ",\"message\":\"" << esc(o->StatusMsg) << "\"}";
        emit("order", out.str());
    }
    void OnRtnTrade(CThostFtdcTradeField* t) override {
        if (!t) return;
        std::ostringstream out; out << std::setprecision(15)
            << "{\"trade_id\":\"" << esc(t->TradeID) << "\",\"order_id\":" << std::atoll(t->OrderRef)
            << ",\"order_ref\":\"" << esc(t->OrderRef) << "\",\"system_no\":\"" << esc(t->OrderSysID)
            << "\",\"instrument\":\"" << esc(t->InstrumentID) << "\",\"exchange\":\"" << esc(t->ExchangeID)
            << "\",\"side\":\"" << (t->Direction == THOST_FTDC_D_Buy ? "B" : "S")
            << "\",\"offset\":\"" << (t->OffsetFlag == THOST_FTDC_OF_Open ? "O" : (t->OffsetFlag == THOST_FTDC_OF_CloseToday ? "T" : "C"))
            << "\",\"price\":" << t->Price << ",\"volume\":" << t->Volume << "}";
        emit("trade", out.str());
    }
    void OnRspQryTradingAccount(CThostFtdcTradingAccountField* a, CThostFtdcRspInfoField* info,
                                int request_id, bool last) override {
        if (failed(info)) { emit_error("td.query_funds", info, request_id); return; }
        if (!a) return;
        std::ostringstream out; out << std::setprecision(15)
            << "{\"account\":\"" << esc(a->AccountID) << "\",\"balance\":" << a->Balance
            << ",\"available\":" << a->Available << ",\"margin\":" << a->CurrMargin
            << ",\"commission\":" << a->Commission << ",\"last\":" << (last ? "true" : "false") << "}";
        emit("fund", out.str());
    }
    void OnRspQryInvestorPosition(CThostFtdcInvestorPositionField* p, CThostFtdcRspInfoField* info,
                                  int request_id, bool last) override {
        if (failed(info)) { emit_error("td.query_positions", info, request_id); return; }
        if (!p) { if (last) emit("position.end", "{}"); return; }
        std::ostringstream out; out << std::setprecision(15)
            << "{\"instrument\":\"" << esc(p->InstrumentID) << "\",\"direction\":\"" << p->PosiDirection
            << "\",\"position\":" << p->Position << ",\"today_position\":" << p->TodayPosition
            << ",\"yd_position\":" << p->YdPosition << ",\"position_cost\":" << p->PositionCost
            << ",\"margin\":" << p->UseMargin << ",\"last\":" << (last ? "true" : "false") << "}";
        emit("position", out.str());
        if (last) emit("position.end", "{}");
    }
    void OnRspQryInstrument(CThostFtdcInstrumentField* i, CThostFtdcRspInfoField* info,
                            int request_id, bool last) override {
        if (failed(info)) { emit_error("td.query_contracts", info, request_id); return; }
        if (!i) return;
        std::ostringstream out; out << std::setprecision(15)
            << "{\"instrument\":\"" << esc(i->InstrumentID) << "\",\"exchange\":\"" << esc(i->ExchangeID)
            << "\",\"name\":\"" << esc(i->InstrumentName) << "\",\"product\":\"" << esc(i->ProductID)
            << "\",\"volume_multiple\":" << i->VolumeMultiple << ",\"price_tick\":" << i->PriceTick
            << ",\"is_trading\":" << (i->IsTrading ? "true" : "false") << ",\"last\":" << (last ? "true" : "false") << "}";
        emit("contract", out.str());
    }
    void OnRspError(CThostFtdcRspInfoField* info, int request_id, bool) override { emit_error("td.response", info, request_id); }

private:
    template <size_t N> static void copy(char (&target)[N], const std::string& value) { std::strncpy(target, value.c_str(), N-1); target[N-1]='\0'; }
    static bool failed(CThostFtdcRspInfoField* info) { return info && info->ErrorID != 0; }
    void authenticate() {
        CThostFtdcReqAuthenticateField req{}; copy(req.BrokerID, broker_); copy(req.UserID, user_id_);
        copy(req.AppID, app_id_); copy(req.AuthCode, auth_code_); copy(req.UserProductInfo, "quant_framework");
        int rc = api_->ReqAuthenticate(&req, ++request_id_); if (rc != 0) emit_local_error("td.authenticate", rc);
    }
    void login() {
        CThostFtdcReqUserLoginField req{}; copy(req.BrokerID, broker_); copy(req.UserID, user_id_); copy(req.Password, password_);
        int rc = api_->ReqUserLogin(&req, ++request_id_); if (rc != 0) emit_local_error("td.login", rc);
    }
    void emit(const char* type, const std::string& payload) { if (callback_) callback_(type, payload.c_str(), user_); }
    void emit_local_error(const char* where, int code) { CThostFtdcRspInfoField info{}; info.ErrorID=code; copy(info.ErrorMsg, "CTP request rejected locally"); emit_error(where, &info, 0); }
    void emit_error(const char* where, CThostFtdcRspInfoField* info, int request_id) {
        std::ostringstream out; out << "{\"where\":\"" << where << "\",\"request_id\":" << request_id
            << ",\"error_code\":" << (info ? info->ErrorID : -1) << ",\"message\":\"" << esc(info ? info->ErrorMsg : "unknown CTP error") << "\"}";
        emit("gateway.error", out.str());
    }
    void emit_order_error(const char* where, const char* order_ref, CThostFtdcRspInfoField* info, int request_id) {
        std::ostringstream out; out << "{\"order_id\":" << std::atoll(order_ref ? order_ref : "0") << ",\"request_id\":" << request_id
            << ",\"order_ref\":\"" << esc(order_ref) << "\",\"status\":\"rejected\",\"error_code\":" << (info ? info->ErrorID : -1)
            << ",\"message\":\"" << esc(info ? info->ErrorMsg : "unknown CTP error") << "\"}";
        emit("order", out.str());
    }

    ctp_event_callback callback_{}; void* user_{}; CThostFtdcTraderApi* api_{};
    std::string broker_, user_id_, password_, app_id_, auth_code_;
    int request_id_{}; int front_id_{}; int session_id_{}; bool ready_{}; std::mutex mutex_;
};
}

CTP_EXPORT void* CTP_CALL ctp_td_create(ctp_event_callback callback, void* user) { try { return new TdBridge(callback,user); } catch (...) { return nullptr; } }
CTP_EXPORT void CTP_CALL ctp_td_destroy(void* handle) { delete static_cast<TdBridge*>(handle); }
CTP_EXPORT int CTP_CALL ctp_td_connect(void* h,const char* f,const char* b,const char* u,const char* p,const char* a,const char* c,const char* flow) { return h ? static_cast<TdBridge*>(h)->connect(f,b,u,p,a,c,flow) : -1; }
CTP_EXPORT int CTP_CALL ctp_td_insert_order(void* h,const char* i,const char* e,char s,char o,char hedge,char type,char tif,int v,int minv,double p,int req,int ref) { return h ? static_cast<TdBridge*>(h)->insert(i,e,s,o,hedge,type,tif,v,minv,p,req,ref) : -1; }
CTP_EXPORT int CTP_CALL ctp_td_cancel_order(void* h,const char* i,const char* e,const char* ref,int front,int session,const char* sys,int req) { return h ? static_cast<TdBridge*>(h)->cancel(i,e,ref,front,session,sys,req) : -1; }
CTP_EXPORT int CTP_CALL ctp_td_query_funds(void* h) { return h ? static_cast<TdBridge*>(h)->query_funds() : -1; }
CTP_EXPORT int CTP_CALL ctp_td_query_positions(void* h) { return h ? static_cast<TdBridge*>(h)->query_positions() : -1; }
CTP_EXPORT int CTP_CALL ctp_td_query_contracts(void* h) { return h ? static_cast<TdBridge*>(h)->query_contracts() : -1; }
