/* Exercise actual guest file operations on a linked overlay and writable saves, and on a packed
 * .zar game (a small fake archive standing in for the ZArchive reader of the GPU library). */
#include "../src/runtime_file.c"
#include <assert.h>
/* The fake archive: / { eboot.bin "BOOT", U2Data/ { big.pak 200000 bytes of i%251 } }. */
struct ZArchive { int unused; };
static struct ZArchive fake;
enum { ROOT, EBOOT, DATA, PAK };
static const char *const fake_names[]={"","eboot.bin","U2Data","big.pak"};
#define PAK_SIZE 200000u
ZArchive *zarchive_open(const char *path) { return strstr(path,"fake.zar") ? &fake : NULL; }
void zarchive_close(ZArchive *archive) { (void)archive; }
uint64_t zarchive_size(const ZArchive *archive) { (void)archive; return 1234; }
const char *zarchive_error(void) { return "not the fake"; }
int64_t zarchive_find(ZArchive *archive, const char *path) {
    (void)archive;
    if (!*path) return ROOT;
    if (!strcasecmp(path,"eboot.bin")) return EBOOT;
    if (!strcasecmp(path,"u2data")) return DATA;
    if (!strcasecmp(path,"u2data/big.pak")) return PAK;
    return ZARCHIVE_NONE;
}
int zarchive_is_file(const ZArchive *archive, int64_t node) { (void)archive; return node==EBOOT || node==PAK; }
uint64_t zarchive_entry_size(const ZArchive *archive, int64_t node) { (void)archive; return node==EBOOT ? 4 : node==PAK ? PAK_SIZE : 0; }
int zarchive_child(ZArchive *archive, int64_t node, uint32_t index, char *name, size_t size, int *is_file) {
    (void)archive;
    int64_t child=node==ROOT && index<2 ? (index ? DATA : EBOOT) : node==DATA && index==0 ? PAK : -1;
    if (child<0) return 0;
    snprintf(name,size,"%s",fake_names[child]); *is_file=zarchive_is_file(&fake,child);
    return 1;
}
uint64_t zarchive_read(ZArchive *archive, int64_t node, uint64_t offset, void *buffer, uint64_t length) {
    uint64_t size=zarchive_entry_size(archive,node);
    if (offset>=size) return 0;
    if (length>size-offset) length=size-offset;
    for (uint64_t i=0;i<length;++i)
        ((unsigned char *)buffer)[i]=node==EBOOT ? (unsigned char)"BOOT"[offset+i] : (unsigned char)((offset+i)%251);
    return length;
}
static void archive_checks(const char *user) {
    runtime_file_configure("/nowhere/fake.zar",user);
    char boot[8]={0};
    int fd=(int)do_open("/app0/EBOOT.BIN",0,0); assert(fd>=3);
    assert(do_read(fd,boot,16)==4 && !strcmp(boot,"BOOT"));
    assert(do_read(fd,boot,16)==0);
    GuestStat info; assert(!do_fstat(fd,&info) && info.size==4 && (info.mode&0170000)==0100000);
    assert(!do_close(fd));
    fd=(int)do_open("u2data/BIG.pak",0,0); assert(fd>=3);
    static unsigned char data[PAK_SIZE];
    assert(do_lseek(fd,-10,2)==(int64_t)PAK_SIZE-10);
    assert(do_read(fd,data,100)==10 && data[0]==(PAK_SIZE-10)%251);
    assert(do_pread(fd,data,PAK_SIZE,0)==(int64_t)PAK_SIZE);
    for (unsigned i=0;i<PAK_SIZE;++i) assert(data[i]==i%251);
    assert(do_write(fd,"x",1)<0);
    assert(!do_close(fd));
    assert(do_open("/app0/eboot.bin",2,0)==-EROFS);
    assert(do_open("/app0/missing.bin",0,0)==-ENOENT);
    assert(do_open("/app0/u2data",1,0)==-EROFS);
    assert(!do_stat("/app0/U2DATA",&info) && (info.mode&0170000)==0040000);
    assert(!do_access("/app0/u2data/big.pak",4) && do_access("/app0/u2data/big.pak",2)==-EROFS);
    char host[64]; assert(translate("/app0/eboot.bin",host,sizeof(host))==ENOENT);
    int dir=(int)do_open("/app0",0x20000,0); assert(dir>=3);
    char entries[1024]; int64_t count=do_getdents(dir,entries,sizeof(entries),NULL); assert(count>0);
    int found=0;
    for (int64_t p=0;p<count;) {
        uint16_t length; memcpy(&length,entries+p+4,2);
        if (!strcmp(entries+p+8,"eboot.bin")) { assert(entries[p+6]==8); ++found; }
        if (!strcmp(entries+p+8,"U2Data")) { assert(entries[p+6]==4); ++found; }
        p+=length;
    }
    assert(found==2 && !do_close(dir));
    int save=(int)do_open("/data/zar-save",0x202,0644); assert(save>=3);   /* saves stay on the host */
    assert(do_write(save,"save",4)==4 && !do_close(save) && !path_op("/data/zar-save",2,0));
    puts("Guest files in a .zar: case-free lookup, reads, seek, stat, listing, read-only PASS");
}
static int32_t guest_errno;
int32_t *runtime_errno(void) { return &guest_errno; }
int32_t runtime_guest_errno(int e) { return e; }
uintptr_t runtime_lookup(const RuntimeExport *table,size_t n,const char *name) {
    for (size_t i=0;i<n;++i) if (!strcmp(table[i].name,name)) return (uintptr_t)table[i].function;
    return 0;
}
int main(void) {
    char root[]="/tmp/bbport-mod-files-XXXXXX";
    assert(mkdtemp(root));
    char game[512],user[512],source[512],link[512];
    snprintf(game,sizeof(game),"%s/game",root);
    snprintf(user,sizeof(user),"%s/user",root);
    snprintf(source,sizeof(source),"%s/mod.dcx",root);
    snprintf(link,sizeof(link),"%s/game/asset.dcx",root);
    assert(!mkdir(game,0755));
    FILE *f=fopen(source,"w"); assert(f); assert(fputs("modded",f)>=0); assert(!fclose(f));
    assert(!symlink(source,link));
    runtime_file_configure(game,user);
    for (int i=0;i<3;++i) {
        const char *path=i==0 ? "/app0/asset.dcx" : i==1 ? "/hostapp/asset.dcx" : "asset.dcx";
        int fd=(int)do_open(path,0,0); assert(fd>=3);
        char content[8]={0}; assert(do_read(fd,content,6)==6 && !strcmp(content,"modded"));
        GuestStat info; assert(!do_stat(path,&info) && info.size==6);
        assert(!do_close(fd));
        assert(do_open(path,2,0)==-EROFS);
        assert(do_open(path,0x400,0)==-EROFS);
        assert(do_truncate(path,0)==-EROFS);
        assert(path_op(path,2,0)==-EROFS);
        assert(do_rename(path,"/data/moved")==-EROFS);
    }
    int dir=(int)do_open("/app0",0x20000,0); assert(dir>=3);
    char entries[1024]; int64_t count=do_getdents(dir,entries,sizeof(entries),NULL); assert(count>0);
    int found=0;
    for (int64_t p=0;p<count;) {
        uint16_t length; memcpy(&length,entries+p+4,2);
        assert(length);
        if (!strcmp(entries+p+8,"asset.dcx")) { assert(entries[p+6]==8); found=1; }
        p+=length;
    }
    assert(found && !do_close(dir));
    int save=(int)do_open("/data/test-save",0x202,0644); assert(save>=3);
    assert(do_write(save,"save",4)==4 && !do_close(save));
    assert(!path_op("/data/test-save",2,0));
    archive_checks(user);
    assert(!unlink(link) && !unlink(source) && !rmdir(game));
    const char *dirs[]={"temp0","download0","data"};
    for (int i=0;i<3;++i) { char p[1024]; snprintf(p,sizeof(p),"%s/%s",user,dirs[i]); assert(!rmdir(p)); }
    assert(!rmdir(user) && !rmdir(root));
    puts("Guest mod files: reads, stat, merged listing, readonly assets and writable saves PASS");
}
