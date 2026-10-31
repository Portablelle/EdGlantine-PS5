#include "core/hle/service/am/service/native_video_layout.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>
using namespace Service::AM;
static void Require(bool ok) { if (!ok) std::abort(); }
int main(int argc, char**) {
    if (argc == 1) {
        std::array<u8, 256> y{};
        std::array<u8, 128> u{}, v{};
        std::array<u8, 1026> out{};
        for (unsigned i=0;i<256;++i) y[i]=i;
        unsigned long long pixels=0;
        for (bool full : {false,true}) for (unsigned cb=0;cb<256;++cb) for(unsigned cr=0;cr<256;++cr) {
            u.fill(cb); v.fill(cr); out.fill(0x5a);
            ConvertNativeVideoYuv709Row(out.data()+1,y.data(),u.data(),v.data(),256,full);
            Require(out.front()==0x5a && out.back()==0x5a);
            for (unsigned x=0;x<256;++x) {
                const auto expected=ConvertNativeVideoYuv709(y[x],cb,cr,full);
                for(unsigned c=0;c<4;++c) if(out[1+x*4+c]!=expected[c]) {
                    std::fprintf(stderr,"mismatch full=%d y=%u u=%u v=%u channel=%u got=%u expected=%u\n",full,x,cb,cr,c,out[1+x*4+c],expected[c]);
                    return 1;
                }
                ++pixels;
            }
        }
        for (unsigned width=0;width<20;++width) for(bool full:{false,true}) {
            std::vector<u8> yy(width),uu((width+1)/2),vv(uu.size()),dst(width*4+2,0x5a);
            for(unsigned i=0;i<width;++i) yy[i]=(i*79+15)%256;
            for(unsigned i=0;i<uu.size();++i) { uu[i]=(i*59+1)%256;vv[i]=(i*41+254)%256; }
            ConvertNativeVideoYuv709Row(dst.data()+1,yy.data(),uu.data(),vv.data(),width,full);
            Require(dst.front()==0x5a && dst.back()==0x5a);
            for(unsigned i=0;i<width;++i) {
                const auto expected=ConvertNativeVideoYuv709(yy[i],uu[i/2],vv[i/2],full);
                for(unsigned c=0;c<4;++c) Require(dst[1+i*4+c]==expected[c]);
            }
        }
        std::printf("PASS %llu exact YUV pixels, both ranges; widths 0..19, exact-sized chroma, tails and unaligned guarded output\n",pixels);
    } else {
        constexpr unsigned width=3840,height=2160;
        std::vector<u8> y(width*height),u(width*height/4),v(u.size()),out(width*height*4);
        unsigned seed=1;
        for(auto* plane:{&y,&u,&v}) for(auto& byte:*plane) {seed=seed*1664525+1013904223;byte=seed>>24;}
        for(bool scalar:{true,false}) {
            const auto start=std::chrono::steady_clock::now();
            unsigned long long checksum=0;
            for(unsigned repeat=0;repeat<16;++repeat) {
                for(unsigned row=0;row<height;++row) {
                    auto* dst=out.data()+size_t{row}*width*4;
                    const auto* yy=y.data()+size_t{row}*width;
                    const auto* uu=u.data()+size_t{row/2}*width/2;
                    const auto* vv=v.data()+size_t{row/2}*width/2;
                    if(scalar) for(unsigned x=0;x<width;++x) {
                        const auto pixel=ConvertNativeVideoYuv709(yy[x],uu[x/2],vv[x/2],false);
                        std::memcpy(dst+size_t{x}*4,pixel.data(),4);
                    } else ConvertNativeVideoYuv709Row(dst,yy,uu,vv,width,false);
                }
                checksum+=out[repeat*7919];
            }
            const double ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()/16;
            std::printf("synthetic host 3840x2160 scalar=%d ms/frame=%.3f checksum=%llu\n",scalar,ms,checksum);
        }
    }
}
