cmake_minimum_required(VERSION 3.18)
project(esunny_v10_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(ESUNNY_TRADE_SDK "" CACHE PATH "Directory containing DstarTradeApi.h and the lib directory")
if(NOT ESUNNY_TRADE_SDK)
  message(FATAL_ERROR "Set -DESUNNY_TRADE_SDK=<official V10 trade SDK directory>")
endif()

add_library(esunny_v10_bridge SHARED esunny_v10_bridge.cpp)
target_include_directories(esunny_v10_bridge PRIVATE "${ESUNNY_TRADE_SDK}/include")

if(WIN32)
  target_link_libraries(esunny_v10_bridge PRIVATE "${ESUNNY_TRADE_SDK}/lib/win/x64/libdstartradeapi.lib")
else()
  target_link_libraries(esunny_v10_bridge PRIVATE "${ESUNNY_TRADE_SDK}/lib/linux/libdstartradeapi.so")
endif()

