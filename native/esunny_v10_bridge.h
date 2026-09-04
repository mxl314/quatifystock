#pragma once

#if defined(_WIN32)
#define ES_EXPORT __declspec(dllexport)
#else
#define ES_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*es_event_callback)(const char *event_type, const char *json_payload, void *user_data);

ES_EXPORT void *es_create(es_event_callback callback, void *user_data);
ES_EXPORT void es_destroy(void *handle);
ES_EXPORT int es_connect(void *handle, const char *ip, const char *account, const char *password,
                         const char *app_id, const char *license_no, const char *log_path,
                         unsigned short port);
ES_EXPORT int es_insert_order(void *handle, const char *contract, unsigned int contract_index,
                              char side, char offset, char hedge, char order_type, char valid_type,
                              unsigned int volume, unsigned int min_volume, double price,
                              unsigned int request_id, long long reference, unsigned int seat_index);
ES_EXPORT int es_cancel_order(void *handle, unsigned long long order_id, const char *system_no,
                              unsigned int request_id, long long reference, unsigned int seat_index);
ES_EXPORT int es_query_funds(void *handle);
ES_EXPORT int es_query_positions(void *handle);

#ifdef __cplusplus
}
#endif

