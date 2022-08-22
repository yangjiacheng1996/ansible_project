#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import sys
import os
import json
import pprint
import logging
import click

# aliyun SDK core 用于创建一个临时客户端操作阿里云，并且通过core对客户端进行设置
from aliyunsdkcore import client
from aliyunsdkcore.acs_exception.exceptions import ClientException
from aliyunsdkcore.acs_exception.exceptions import ServerException

# 查询账号上SLB实例信息
from aliyunsdkslb.request.v20140515 import DescribeLoadBalancersRequest
from aliyunsdkslb.request.v20140515 import DescribeLoadBalancerAttributeRequest

# 操作虚拟服务器组的request类
from aliyunsdkslb.request.v20140515 import DescribeVServerGroupAttributeRequest  # 读取所有虚拟服务器条目
from aliyunsdkslb.request.v20140515 import AddVServerGroupBackendServersRequest  # 添加多条虚拟服务器条目
# modify是用于修改多条虚拟服务器条目，将服务器实例id换成另一个，如果只想修改权重，则使用SetVServerGroupAttributeRequest
# from aliyunsdkslb.request.v20140515 import ModifyVServerGroupBackendServersRequest
from aliyunsdkslb.request.v20140515 import RemoveVServerGroupBackendServersRequest # 删除多条虚拟服务器条目
# 修改虚拟服务器条目的权重，使用下面这个类
from aliyunsdkslb.request.v20140515 import SetVServerGroupAttributeRequest

# ECS相关
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkecs.request.v20140526.DescribeRegionsRequest import DescribeRegionsRequest
from aliyunsdkecs.request.v20140526.StartInstanceRequest import StartInstanceRequest


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                    datefmt='%a %d %b %Y %H:%M:%S')

class SLB_operation:
    def __init__(self, accessKEY, secretKEY, regionID="cn-shanghai"):
        self.accessKEY = accessKEY
        self.secretKEY = secretKEY
        self.regionID = regionID
        self.aliyun_client = client.AcsClient(self.accessKEY, self.secretKEY, self.regionID)

    def describe_load_balancer(self, load_balancer_id: str):
        """
        函数功能: 传入slb实例id，返回slb实例的简要信息
        load_balancer_id: 负载均衡实例的id，类型字符串。
        """
        # 实例化请求对象
        request = DescribeLoadBalancersRequest.DescribeLoadBalancersRequest()
        # 配置请求，填入负载均衡实例的ID
        request.set_LoadBalancerId(load_balancer_id)
        # 发送请求，返回json
        return self.__send_request(request)

    def describe_load_balancer_attribute(self, load_balancer_id: str):
        '''
        函数功能：给出负载均衡实例id，返回指定负载均衡实例的详细信息
        load_balancer_id: 负载均衡实例的id，类型字符串。
        '''
        # 实例化请求对象
        request = DescribeLoadBalancerAttributeRequest.DescribeLoadBalancerAttributeRequest()
        # 配置请求，填入负载均衡实例的ID
        request.set_LoadBalancerId(load_balancer_id)
        # 发送请求，返回json
        return self.__send_request(request)

    def describe_virtual_server_group(self, VServerGroupId: str):
        """
        函数功能: 给出某个虚拟服务器组的分组id（group id），返回这个虚拟服务器组的信息,包括服务器id，端口，权重，组名等
        VServerGroupId:  虚拟服务器组的组id，类型字符串，格式类似于 rsp-uf6x5bmukwo8p
        """
        # 实例化请求对象
        request = DescribeVServerGroupAttributeRequest.DescribeVServerGroupAttributeRequest()
        # 配置请求，填入虚拟服务器组的组id，id的样子是这样：rsp-uf6x5bmukwo8p
        request.add_query_param('VServerGroupId', VServerGroupId)
        # request.add_query_param('RegionId', self.regionID)
        # 发送请求，返回json
        return self.__send_request(request)

    def delete_server_in_virtual_server_group(self, VServerGroupId: str, ServerId: str):
        """
        函数功能：传入虚拟服务器组id和服务器实例id，函数会把这台服务器的所有端口从这个虚拟服务器组中摘除。摘除后会再检查一次。
        VServerGroupId: 虚拟服务器组id，
        ServerId: 服务器实例id。
        这个服务器可以使阿里云的ecs，也可以是容器对象eas或其他服务。
        """
        # 先查询某个虚拟服务器组已有的所有虚拟服务器信息
        vservergroup_info = self.describe_virtual_server_group(VServerGroupId)
        backendserver_list = vservergroup_info["BackendServers"]['BackendServer']
        # 将虚拟服务器组中和某实例有关的所有条目检索出来，稍后会删除这些条目。（使用python列表推导式，速度更快）
        want_delete_items = [item for item in backendserver_list if item["ServerId"] == ServerId]
        if not want_delete_items:
            print("虚拟服务器组中没有找到你想摘除的这个实例，不做任何处理。")
            return True
        else:
            print("现在开始，从虚拟服务器组 %s 里面删除所有关于实例 %s 的信息，将要删除的信息如下：" % (VServerGroupId, ServerId))
            pprint.pprint(want_delete_items)
            # 实例化请求对象，这个request专门用于删除虚拟服务器组条目
            request = RemoveVServerGroupBackendServersRequest.RemoveVServerGroupBackendServersRequest()
            # 配置请求，别问我怎么知道这么配的，我是看源码的。光标打到RemoveVServerGroupBackendServersRequest，再按ctrl+B
            request.add_query_param('VServerGroupId', VServerGroupId)
            request.add_query_param('BackendServers', want_delete_items)
            # 发送请求，返回json
            response_json = self.__send_request(request)
            items_after_delete = response_json["BackendServers"]['BackendServer']
            dirty_data = [item for item in items_after_delete if item["ServerId"] == ServerId]
            result = True if not dirty_data else False
            print("是否删除成功？%s" % str(result))
            return result

    def add_upstream_in_virtual_server_group(self, VServerGroupId: str, ServerId: str, Port: int, Weight=100,
                                             Type="ecs"):
        """
        函数功能： 向虚拟服务器组中插入一个负载均衡条目。需要传入的参数有: 虚拟服务器组id、服务器实例id、端口、权重、类型。
        添加前会检查是否已经存在，如果不存在则添加条目，如果已则更新权重。
        添加后会检查一次。
        VServerGroupId: 虚拟服务器组id。
        ServerId: 服务器实例id。
        Port: 开放的端口
        Weight: 这个端口的权重
        Type: 服务器实例的类型，有ecs、eas等等。
        """
        # 先查询某个虚拟服务器组已有的所有虚拟服务器条目信息
        vservergroup_info = self.describe_virtual_server_group(VServerGroupId)
        backendserver_list = vservergroup_info["BackendServers"]['BackendServer']
        # 检查是否已有相同的实例和端口
        same_server_port = [item for item in backendserver_list if
                            item["ServerId"] == ServerId and item["Port"] == Port]
        # 如果没有相同实例和端口，则选择Add请求添加一条，如果已有则选择Set请求。
        if not same_server_port:
            # 实例化Add请求对象
            request = AddVServerGroupBackendServersRequest.AddVServerGroupBackendServersRequest()
            print("条目不存在，创建条目。")
        else:
            # 实例化Set请求对象
            request = SetVServerGroupAttributeRequest.SetVServerGroupAttributeRequest()
            print("条目已存在，更新条目。")
        backend_server_item = [{'Port': Port, 'ServerId': ServerId, 'Weight': Weight, 'Type': Type}]
        request.add_query_param('VServerGroupId', VServerGroupId)
        request.add_query_param('BackendServers', backend_server_item)
        response_json = self.__send_request(request)
        result = True if response_json['BackendServers']['BackendServer'] == backend_server_item else False
        return result

    def __send_request(self, request):
        retry = 3  # 尝试发送请求,失败则重试，最多3次
        counter = 0
        # set_accept_format方法是在SDK的父类里面的，而任何request类都继承了这个父类。
        # 所以发送请求时任何一个request的响应格式都可以设置，我这里统一成json格式。查看阿里云SDK源码请自行ctrl+B。
        request.set_accept_format('json')
        while counter < retry:
            try:
                # 发送调用请求并接收返回数据，数据是个json字符串
                response_str = self.aliyun_client.do_action_with_exception(request)
                response_json = json.loads(response_str)
                # pprint.pprint(response_json)
                # 返回结果
                return response_json
            except ServerException as se:
                print(se)
            except ClientException as ce:
                print(ce)
            except Exception as e:
                logging.error(e)
            finally:
                counter += 1
        raise Exception("请求发不了，报错了 >_< ")

class ECS_operation:
    def __init__(self, accessKEY, secretKEY, regionID="cn-shanghai"):
        """
        客户端初始化。
        想要实例化出一个客户端对象需要传入3个函数，AccessKey ID，AccessKey Secret , 地域 ID
        """
        self.accessKEY = accessKEY
        self.secretKEY = secretKEY
        self.regionID = regionID
        self.aliyun_client = client.AcsClient(self.accessKEY, self.secretKEY, self.regionID)

    def supported_regions(self):
        """
        查询客户端账号能到达的所有地域，返回一个字典
        """
        request = DescribeRegionsRequest()
        try:
            response_detail = self.__send_request(request)
            return response_detail
        except Exception as e:
            logging.error(e)


    def query_instance_id_by_primary_ip(self, primary_ip, regionID="cn-shagnhai"):
        """
        功能: 给出区域id和ECS实例的主ipv4地址，返回这个实例的实例id
        primary_ip: 主网地址，一般就是ECS服务器的内网地址。对应服务器中eth0网卡的ipv4地址。
        regionID: 阿里云地区的区域id。
        """
        all_instances_info = self.region_all_instances_info(regionID)
        for instance in self.region_all_instances_info(regionID):
            if instance['NetworkInterfaces']["NetworkInterface"][0]["PrimaryIpAddress"] == primary_ip:
                instance_id = instance["InstanceId"]
                return instance_id
        logging.error("检索了所有ECS实例信息，没有找到你给出的ip地址。请确定查询所使用的IP地址格式和信息正确，没有空格，")
        raise IOError("ip数据源错误")

    def region_all_instances_info(self, regionID):
        """
        功能：函数传入一个区域id，返回这个区域中所有的ECS实例的详细信息，原理是使用__page_show_ecs_instances函数一页一页查询汇总。
        regionID: 区域id号，上海就是 cn-shanghai
        """
        pagenum = 1
        pagesize = 100
        gather_info = list(dict(self.__page_show_ecs_instances(regionID, pagenum, pagesize))['Instances']['Instance'])
        while True:
            pagenum += 1
            current_page = self.__page_show_ecs_instances(regionID, pagenum, pagesize)
            if len(current_page['Instances']['Instance']) == 0:
                # logging.info("page is empty , do not continue searching")
                break
            elif current_page['TotalCount'] < 100:
                print("current page instances count : %d" % current_page['TotalCount'])
                gather_info.extend(list(current_page['Instances']['Instance']))
                break
            else:
                gather_info.extend(list(current_page['Instances']['Instance']))
        return gather_info

    def __page_show_ecs_instances(self, regionID, pagenum=1, pagesize=100):
        """
        函数传入一个 regionID, 按页查询账号在这个地域下的ECS服务器。
        regionID: 区域id
        pagenum: 页码。客户端查询ECS实例是通过网页翻页进行的，所以需要规定访问第几页。
        pagesize: 每页显示多少个实例。 客户端支持最大每页显示100个实例。建议100不动。
        """
        request = DescribeInstancesRequest()
        try:
            request.set_PageNumber(pagenum)
            request.set_PageSize(pagesize)
            page_instance_info = self.__send_request(request)
            return page_instance_info
        except Exception as e:
            raise SyntaxError("查询ECS，页码Size有误")

    def check_instance_is_running(self,regionID,instance_id):
        """
        函数功能： 给出区域id和实例id，如果实例是运行状态则返回True，不是则返回False，查无此实例，程序报错中断。
        """
        all_info = self.region_all_instances_info(regionID)
        for instance in all_info:
            if instance['InstanceId'] == instance_id and instance['Status'] == 'Running':
                return True
            elif instance['InstanceId'] == instance_id and instance['Status'] != 'Running':
                return False
        raise IOError("根据您的给出的instance id和区域 id，在账号中未找到对应的ECS服务器。")

    def make_sure_instance_is_running(self,regionID,instance_id):
        """
        函数功能： 传入区域id和实例id,检查这个实例的状态，如果是停机状态就开机把停机状态的
        """
        if not self.check_instance_is_running(regionID,instance_id):
            self.start_instance(instance_id)
        return None

    def start_instance(self,instance_id):
        request = StartInstanceRequest()
        request.set_InstanceId(instance_id)
        self.__send_request(request)
        time.sleep(120)
        return True

    def __send_request(self,request):
        retry = 3  # 尝试发送请求,失败则重试，最多3次
        counter = 0
        request.set_accept_format('json')
        while counter < retry:
            try:
                # 发送调用请求并接收返回数据，数据是个json字符串
                response_str = self.aliyun_client.do_action_with_exception(request)
                response_json = json.loads(response_str)
                # pprint.pprint(response_json)
                # 返回结果
                return response_json
            except ServerException as se:
                print(se)
            except ClientException as ce:
                print(ce)
            except Exception as e:
                logging.error(e)
            finally:
                counter += 1
        raise Exception("请求发不了，报错了 >_< ")

@click.group()
def main():
    print("******* This is a Tool to control Aliyun services ******\n")
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                        datefmt='%a %d %b %Y %H:%M:%S')
    # logging.basicConfig(level=logging.DEBUG, filename="output.log",
    #                     format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
    #                     datefmt='%a,%d %b %Y %H:%M:%S')


@click.command()
@click.option("-a", "--accesskey", help="某个主账号或RAM子账号生成的accesskey", required=True, default="aaaaaa")
@click.option("-s", "--secretkey", help="某个主账号或RAM子账号生成的secretkey,与accesskey成对", required=True, default="ssssss")
@click.option("-v", "--vservergroupid", help="虚拟服务器组id", required=False, default="gggggg")
@click.option("-i", "--ip", help="后端服务器实例主私网ip", required=False, default="xxx.xxx.xxx.xxx")
@click.option("-p", "--port", help="暴露端口", required=False, default="ppppp")
@click.option("-r", "--regionid", help="服务器实例所在的区域id", required=True, default="cn-shanghai")
@click.option("-t", "--type", help="后端服务器类型", required=False, default="ecs")
@click.option("-w", "--weight", help="端口权重", required=False, default="100")
def addport(accesskey, secretkey, regionid, vservergroupid, ip, port, type, weight):
    if not port.isdigit():
        raise SystemError("-p/--port 参数错误，此参数需要传入整数，却接收到字母或特殊字符。")
    elif not weight.isdigit():
        raise SystemError(("-w/--weight 参数错误，此参数需要传入整数，却接收到字母或特殊字符。"))
    else:
        ecs_client = ECS_operation(accesskey, secretkey, regionid)
        instance_id = ecs_client.query_instance_id_by_primary_ip(ip,regionID=regionid)
        slb_client = SLB_operation(accesskey, secretkey, regionid)
        slb_client.add_upstream_in_virtual_server_group(vservergroupid, instance_id, port, weight, Type=type)


@click.command()
@click.option("-a", "--accesskey", help="某个主账号或RAM子账号生成的accesskey", required=True, default="aaaaaa")
@click.option("-s", "--secretkey", help="某个主账号或RAM子账号生成的secretkey,与accesskey成对", required=True, default="ssssss")
@click.option("-v", "--vservergroupid", help="虚拟服务器组id", required=False, default="gggggg")
@click.option("-i", "--ip", help="后端服务器实例主私网ip", required=False, default="xxx.xxx.xxx.xxx")
@click.option("-r", "--regionid", help="服务器实例所在的区域id", required=True, default="cn-shanghai")
def removeserver(accesskey, secretkey, regionid,vservergroupid, ip):
    ecs_client = ECS_operation(accesskey, secretkey, regionid)
    instance_id = ecs_client.query_instance_id_by_primary_ip(ip, regionID=regionid)
    slb_client = SLB_operation(accesskey, secretkey, regionid)
    slb_client.delete_server_in_virtual_server_group(vservergroupid,instance_id)

main.add_command(removeserver)
main.add_command(addport)

if __name__ == '__main__':
    main()


