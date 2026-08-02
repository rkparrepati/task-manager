import math
import os
import re
import json
import time
from datetime import datetime,timedelta
from dotenv import load_dotenv
load_dotenv()
import pandas as pd
import numpy as np
from decimal import Decimal, ROUND_HALF_UP
from utils.custom_logger import log_info, log_error, log_warning, log_debug
from django.views import View
from django.http import JsonResponse, FileResponse
from django.db import transaction
from django.db.models import Min, Max
from django.db.models import F
from google.api_core import exceptions,retry,retry_async
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions,status
from rest_framework.authentication import TokenAuthentication
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.decorators import method_decorator
from UPSDDA.azure_entra_id_decorator import azure_token_required, azure_token_required_async
from django.db.models import OuterRef, Subquery, Exists, DecimalField, Value
from io import StringIO
import tempfile
import requests
import csv
from io import StringIO
import threading
import asyncio
import ast
from asgiref.sync import sync_to_async
from google.cloud import bigquery,storage
# from google.oauth2 import service_account  # Legacy JSON-key auth path disabled; using ADC.

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema

from AnalyzerList.models import TScenarioHierarchy, TUserProfile,TPricingProfileSummary,TScenario,TAnalyzerScenarioBid,VBasicIncentivePlan,VIncentivePlan,TAnalyzerPacket,TAccessorialHierarchy,TServiceHierarchy,TopportunityPldFileAccounts,TOpportunityPldFile, TPricingServiceFeatureMapping

project_id = os.environ['PROJECT_ID']
database_id = os.environ['GCPR_SUMMARY_DATABASE']
shipping_profile_summary = f"{project_id}.{database_id}.{os.environ['TABLE_SUMMARY_SHIPPING_PROFILE']}"
accessorial_summary = f"{project_id}.{database_id}.{os.environ['TABLE_SUMMARY_ACCESSORIAL']}"

client=bigquery.Client()

            
REVENUE_FIELD_MAP    = {
                                "Fuel Surcharge": {
                                    "net": "FuelSurchargeNetUSD",
                                    "gross": "FuelSurchargeGrossUSD",
                                    "cost": "FuelSurchargeBaseBidCost",
                                    "marginal": "FuelSurchargeMarginalCost"
                                },
                                "Transportation Charges": {
                                    "net": "TransportationChargesNetUSD",
                                    "gross": "TransportationChargesGrossUSD",
                                    "cost": "TransportationChargesBaseBidCost",
                                    "marginal": "TransportationChargesMarginalCost"
                                },
                                "Pickup And Delivery": {
                                    "net": "PickupAndDeliveryNetUSD",
                                    "gross": "PickupAndDeliveryGrossUSD",
                                    "cost": "PickupAndDeliveryBaseBidCost",
                                    "marginal": "PickupAndDeliveryMarginalCost"
                                },
                                "Returns": {
                                    "net": "ReturnsNetUSD",
                                    "gross": "ReturnsGrossUSD",
                                    "cost": "ReturnsBaseBidCost",
                                    "marginal": "ReturnsMarginalCost"
                                },
                                "Other Charges": {
                                    "net": "OtherChargesNetUSD",
                                    "gross": "OtherChargesGrossUSD",
                                    "cost": "OtherChargesBaseBidCost",
                                    "marginal": "OtherChargesMarginalCost"
                                },
                                "Custom Brokerage": {
                                    "net": "CustomBrokerageNetUSD",
                                    "gross": "CustomBrokerageGrossUSD",
                                    "cost": "CustomBrokerageBaseBidCost",
                                    "marginal": "CustomBrokerageMarginalCost"
                                }
                            }


def safe_ratio(numerator, denominator, default=0.0, return_valid=False):
    """Safely divide numerator by denominator, returning default when invalid."""
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        valid = np.isfinite(den) & (den != 0)
        result = np.divide(num, den, out=np.full_like(num, default, dtype=float), where=valid)
    result = np.where(np.isfinite(result), result, default)
    if return_valid:
        return result, valid
    return result

def sanitize_numeric(container, default=0.0):
    """Replace NaN/Inf values with a sensible default."""
    if isinstance(container, pd.DataFrame):
        numeric_cols = container.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            container[col] = np.nan_to_num(container[col], nan=default, posinf=default, neginf=default)
        return container
    if isinstance(container, pd.Series):
        cleaned = np.nan_to_num(container.to_numpy(dtype=float), nan=default, posinf=default, neginf=default)
        return pd.Series(cleaned, index=container.index)
    return container

def to_float(value, default=0.0):
    """Coerce a value to float; fall back to default on failure."""
    try:
        if value is None:
            return default
        if isinstance(value, float) and np.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default

def getScenarioHierarchy(scenario_system_number):
    func_start_time = time.time()
    try:
        check=False
        scnnum=0
        while not check:
            query_start_time = time.time()
            scenario_hierarchy = TScenarioHierarchy.objects\
                .filter(ScenarioSystemNumber=scenario_system_number)\
                .values_list('BaseScenarioSystemNumber',flat=True)
            if not scenario_hierarchy:
                # No further hierarchy — use current scenario's ScenarioNumber
                scenario = TScenario.objects.get(ScenarioSystemNumber=scenario_system_number)
                return scenario.ScenarioNumber
            log_info("Query executed", context=f"getScenarioHierarchy - Fetching BaseScenarioSystemNumber for ScenarioSystemNumber {scenario_system_number}", trans_tm=int((time.time() - query_start_time) * 1000))
            
            query_start_time = time.time()
            scenario = TScenario.objects\
                .get(ScenarioSystemNumber=scenario_hierarchy[0])
            log_info("Query executed", context=f"getScenarioHierarchy - Fetching TScenario for ScenarioSystemNumber {scenario_hierarchy[0]}", trans_tm=int((time.time() - query_start_time) * 1000))
            
            check = scenario.SummaryGeneratedIndicator
            scenario_system_number = scenario_hierarchy[0]
            scnnum = scenario.ScenarioNumber
        
        log_info("getScenarioHierarchy function completed", context=f"getScenarioHierarchy - Successfully retrieved scenario number {scnnum}", trans_tm=int((time.time() - func_start_time) * 1000))
        return scnnum
    except Exception as e:
        log_error("getScenarioHierarchy function failed", context=f"getScenarioHierarchy - Error fetching scenario hierarchy for ScenarioSystemNumber {scenario_system_number}", exc=e, trans_tm=int((time.time() - func_start_time) * 1000))
        return None

def get_annualization_factor(analyzer_id, default=1.0, account_number=None):
    """
    Retrieve the annualization factor for a given analyzer packet.


    Resolution order when account_number IS provided:
      - Starts with "TM" → Opportunity PLD (file-specific via TopportunityPldFileAccounts)
      - Any other value  → Historical PLD (TAnalyzerPacket) — explicit non-TM account
                          always means HPLD even in mixed HPLD/OPLD packets

    Resolution order when account_number is NOT provided (None):
      1. TOpportunityPldFile exists for the packet → use its AF (OPLD packet-level)
      2. Otherwise                                 → TAnalyzerPacket (HPLD)
      Used by views that aggregate across all accounts with no per-account context.



    Parameters
    ----------
    analyzer_id : int or str
        The AnalyzerPacketSystemNumber identifying the analyzer packet.
    default : float, optional

        Returned when the factor is null or the record is not found. Default 1.0.
    account_number : str or None, optional
        Billing account number.  Pass None (or omit) when no specific account is known.


    Returns
    -------
    float
        The annualization factor, or ``default`` (1.0) on any error.
    """
    try:


        if account_number is not None and str(account_number).strip():
            # Explicit account provided — route strictly by TM prefix
            if str(account_number).upper().startswith("TM"):
                # Opportunity PLD: resolve via temp account number (file-specific)


                acct_obj = TopportunityPldFileAccounts.objects.filter(
                    TemporaryAccountNumber=account_number,
                    OpportunityPldFileSystemNumber__AnalyzerPacketSystemNumber=int(analyzer_id)
                ).select_related('OpportunityPldFileSystemNumber').first()
                if acct_obj is not None:
                    factor = acct_obj.OpportunityPldFileSystemNumber.AnnualizationDerivedFactorQuantity
                    if factor is not None:
                        return float(factor)
                return default


            # Non-TM account → always Historical PLD, regardless of whether OPLD
            # files also exist on this packet (mixed HPLD/OPLD scenario)


        packet = TAnalyzerPacket.objects.get(AnalyzerPacketSystemNumber=int(analyzer_id))
        factor = packet.AnnualizationDerivedFactorQuantity
        if factor is None:
            return default
        return float(factor)


        # No account provided: try OPLD packet-level fallback first, then HPLD
        opp_file = TOpportunityPldFile.objects.filter(
            AnalyzerPacketSystemNumber=int(analyzer_id)
        ).first()
        if opp_file is not None:
            factor = opp_file.AnnualizationDerivedFactorQuantity
            if factor is not None:
                return float(factor)
        # Historical PLD

        packet = TAnalyzerPacket.objects.get(AnalyzerPacketSystemNumber=int(analyzer_id))
        factor = packet.AnnualizationDerivedFactorQuantity
        if factor is None:
            return default
        return float(factor)

    except Exception:
        return default

@method_decorator(azure_token_required,name='dispatch')
class ScenarioList(APIView):

    allowed_methods = ['GET']
    def get(self, request, analyzerpacketsystemnumber):
        start_time=time.time()
        try:
            log_info("Scenario List API started", context="ScenarioList.get - API execution started")
            
            query_start_time = time.time()
            user_number = TUserProfile.objects.filter(CloudUserIdentificationNumber=request.claims['EmpID'])
            log_info("Query executed", context="ScenarioList.get - Fetching user profile for authentication", trans_tm=int((time.time() - query_start_time) * 1000))
            
            query_start_time = time.time()
            scenario_list = TScenario.objects.filter(AnalyzerPacketSystemNumber=analyzerpacketsystemnumber).values('ScenarioSystemNumber','ScenarioName')
            log_info("Query executed", context=f"ScenarioList.get - Fetching scenarios for AnalyzerPacketSystemNumber {analyzerpacketsystemnumber}", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if scenario_list.exists():
                log_info("ScenarioList API completed successfully", context=f"ScenarioList.get - Found {scenario_list.count()} scenarios", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"scenarioNames" : scenario_list })
            else:
                log_warning("ScenarioList API completed with no results", context=f"ScenarioList.get - No scenarios found for AnalyzerPacketSystemNumber {analyzerpacketsystemnumber}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': 'Status Code not found'}, status=status.HTTP_404_NOT_FOUND)   
        except Exception as e:
            log_error("ScenarioList API failed", context=f"ScenarioList.get - Error occurred while fetching scenarios", exc=e, trans_tm=int((time.time() - start_time) * 1000))
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(azure_token_required,name='dispatch')
class ScenarioSummaryView(APIView):
    allowed_methods = ['GET']
    @swagger_auto_schema(
        operation_description="Returns details for a shipping profile summary with filters applied.",
        responses={
            200: openapi.Response(
                description="Successful retrieval of shipping profile summary",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Items(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "ScenarioSystemNumber": openapi.Schema(type=openapi.TYPE_INTEGER),
                            "Total": openapi.Schema(type=openapi.TYPE_OBJECT,
                                properties={
                                    "ADV": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "BaseFrtDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "TotalDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "RPP": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "Revenue": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "OR": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                    "Profit": openapi.Schema(type=openapi.TYPE_NUMBER, format="float")
                                }
                            ),
                            "BidLevel": openapi.Schema(type=openapi.TYPE_ARRAY,
                                items=openapi.Items(type=openapi.TYPE_OBJECT,
                                    properties={
                                        "AnalyzerBidName": openapi.Schema(type=openapi.TYPE_STRING),
                                        "AnalyzerScenarioBidSystemNumber": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "ADV": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "BaseFrtDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "TotalDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "RPP": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "Revenue": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "OR": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "Profit": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                        "service_level": openapi.Schema(type=openapi.TYPE_OBJECT,
                                            properties={
                                                "service_code": openapi.Schema(type=openapi.TYPE_STRING),
                                                "service_name": openapi.Schema(type=openapi.TYPE_STRING),
                                                "ADV": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "BaseFrtDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "TotalDisc": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "RPP": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "Revenue": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "OR": openapi.Schema(type=openapi.TYPE_NUMBER, format="float"),
                                                "Profit": openapi.Schema(type=openapi.TYPE_NUMBER, format="float")
                                            }
                                        )
                                    }
                                )
                            )
                        }
                    )
                )
            ),
            400: openapi.Response(
                description="Bad request due to invalid parameters or internal error",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "message": openapi.Schema(type=openapi.TYPE_STRING, example="An error occurred")
                    }
                )
            )
        },
        tags=['Shipping Profile Summary']
    )

    def get(self,request):
        start_time=time.time()
        try:
            log_info("ScenarioSummaryView API started", context="ScenarioSummaryView.get - API execution started")
            empId=request.claims['EmpID']
            
            query_start_time = time.time()
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Query executed", context=f"ScenarioSummaryView.get - Fetching user profile for EmpId {empId}", trans_tm=int((time.time() - query_start_time) * 1000))
            if not user_number:
                log_error("ScenarioSummaryView API failed", context=f"ScenarioSummaryView.get - User not accessible for EmpId {empId}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error":"Inaccessible"},status=status.HTTP_400_BAD_REQUEST)
            AnalyzerPktId = request.GET.get('AnalyzerPacketSystemNumber')
            if not AnalyzerPktId:
                log_error("ScenarioSummaryView API failed", context="ScenarioSummaryView.get - Analyzer Packet Id missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing analyzerpacketsystemnumber"}, status=status.HTTP_400_BAD_REQUEST)
            costBasis = request.GET.get('CostBasis')
            if not costBasis:
                log_error("ScenarioSummaryView API failed", context="ScenarioSummaryView.get - Cost basis missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing costBasis"}, status=status.HTTP_400_BAD_REQUEST)
            scenario_sys_num = request.GET.get('ScenarioSystemNumber')
            if not scenario_sys_num:
                log_error("ScenarioSummaryView API failed", context="ScenarioSummaryView.get - Scenario System Number missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing scenario system number"}, status=status.HTTP_400_BAD_REQUEST)
            scenario_sys_num = ast.literal_eval(scenario_sys_num)
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='TotalBaseBidFrieghtCost'
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='TotalMarginalFrieghtCost'
            else:
                raise Exception(f"Incorrect Cost Basis")     
            revenueBasis = request.GET.get('RevenueBasis')
            if not revenueBasis:
                log_error("ScenarioSummaryView API failed", context="ScenarioSummaryView.get - Revenue basis missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Revenue Basis"}, status=status.HTTP_400_BAD_REQUEST)
            
            query_start_time = time.time()
            scenario_bid_details=TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber__in=scenario_sys_num
                                     ).values(
                        'ScenarioSystemNumber',
                        'AnalyzerBidName',
                        'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber',
                        'PricingProfileSummarySystemNumber__RevenueAdjustmentValueAmount'
                    )
            log_info("Query executed", context=f"ScenarioSummaryView.get - Fetching scenario bid details for scenario system numbers", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not scenario_bid_details:
                log_error("ScenarioSummaryView API failed", context=f"ScenarioSummaryView.get - No bid details found for scenario system numbers {scenario_sys_num}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No bids found for given scenario"}, status=status.HTTP_400_BAD_REQUEST)
            scenario_bid_details=pd.DataFrame(scenario_bid_details)
            scenario_bid_details.rename(columns={
                'ScenarioSystemNumber__ScenarioName': 'ScenarioName',
                'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber',
                'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber',
                'PricingProfileSummarySystemNumber__RevenueAdjustmentValueAmount':'RevenueAdjustmentValueAmount'
                }, inplace=True)
            scenario_bid_details['BidNumber']=scenario_bid_details['BidNumber'].astype(str)
            
            query_start_time = time.time()
            scee_bid = TScenario.objects.filter(
                ScenarioSystemNumber__in=scenario_sys_num
            ).values(
                'ScenarioName',
                'ScenarioSystemNumber',
                'SummaryGeneratedIndicator',
                'ScenarioNumber'
            )
            log_info("Query executed", context=f"ScenarioSummaryView.get - Fetching scenario details for scenario system numbers", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not scee_bid:
                log_error("ScenarioSummaryView API failed", context=f"ScenarioSummaryView.get - No scenario found for scenario system number {scenario_sys_num}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No scenario found for given scenario system number"}, status=status.HTTP_400_BAD_REQUEST)
            scee_bid_df = pd.DataFrame(scee_bid)
            scee_bid_df['ScenarioNumber'] = scee_bid_df['ScenarioNumber'].astype(str)
            # Each scenario's own ScenarioNumber is always used as the BigQuery lookup key.
            # getScenarioHierarchy was previously used for SummaryGeneratedIndicator=False scenarios,
            # but it caused scenarios sharing the same parent to both resolve to the
            # same ScenarioNumber → identical BigQuery rows → identical output.
            scee_bid_df['TempScenarioNumber'] = scee_bid_df['ScenarioNumber'].astype(str)
            scenarioNo=scee_bid_df['TempScenarioNumber'].unique()
            scenarioNo = f"('{scenarioNo[0]}')" if len(scenarioNo) == 1 else "(" + ",".join(f"'{str(b)}'" for b in scenarioNo) + ")"
            if revenueBasis in ['All', '"All"',"'All'"]:
                selected_net_fields = [v["net"] for v in REVENUE_FIELD_MAP.values()]
                selected_gross_fields = [v["gross"] for v in REVENUE_FIELD_MAP.values()]
                selected_cost_fields = [v["cost"] for v in REVENUE_FIELD_MAP.values()]
                selected_marginal_fileds=[v["marginal"] for v in REVENUE_FIELD_MAP.values()]
            else:
                try:
                    revenueBasis = ast.literal_eval(revenueBasis)
                except Exception:
                    revenueBasis = [revenueBasis]
                selected_net_fields = [REVENUE_FIELD_MAP[f]["net"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_gross_fields = [REVENUE_FIELD_MAP[f]["gross"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_cost_fields = [REVENUE_FIELD_MAP[f]["cost"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_marginal_fileds=[REVENUE_FIELD_MAP[f]["marginal"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
            # Build expressions
            net_expr =  ",".join([f"  SUM({col}) as {col}" for col in selected_net_fields])
            gross_expr =  ",".join([f"  SUM({col}) as {col}" for col in selected_gross_fields])
            cost_expr = f",".join([f"  SUM({col}) as {col}" for col in selected_cost_fields])
            marginal_expr=f",".join([f"  SUM({col}) as {col}" for col in selected_marginal_fileds])
            costBasis_field=f"sum({costBasis}) as {costBasis}"
            
            query=f"""SELECT
                    BidNumber,ServiceCode,Mode,ScenarioNumber AS TempScenarioNumber,
                    BillToAccountNumber,
                    Sum(ADV) as ADV,
                    Sum(BaseNetReportingAmount) AS BaseNetReportingAmount,
                    Sum(BaseGrossReportingAmount) as BaseGrossReportingAmount,
                    {costBasis_field},
                    {cost_expr},
                    {net_expr},
                    {gross_expr},
                    {marginal_expr},
                    Sum(PackageQuantity) as  PackageQuantity
                    FROM {shipping_profile_summary}
                    WHERE AnalyzerPacketID = '{str(AnalyzerPktId)}'
                    and ScenarioNumber in {scenarioNo}
                    Group By BidNumber,ScenarioNumber,ServiceCode,Mode,BillToAccountNumber"""
            
            query_start_time = time.time()
            result_service=client.query(query=query).to_dataframe()
            log_info("BigQuery executed", context="ScenarioSummaryView.get - Fetching shipping profile summary from BigQuery", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if result_service.empty:
                log_info("ScenarioSummaryView API completed", context="ScenarioSummaryView.get - No data found for selected scenarios", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data found for the selected scenarios. Ensure all selected scenarios have been rated."}, status=status.HTTP_200_OK)
            # Per-row AF: handles mixed HPLD/OPLD accounts before aggregation
            result_service['PackageQuantity'] = result_service['PackageQuantity'].astype(float)
            result_service["_af"] = result_service["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(AnalyzerPktId, account_number=str(acct))
            )
            result_service["PackageQuantity"] = result_service["PackageQuantity"] * result_service["_af"]
            result_service.drop(columns=["_af", "BillToAccountNumber"], inplace=True)
            _ss_sum_cols = list(dict.fromkeys(
                ["ADV", "BaseNetReportingAmount", "BaseGrossReportingAmount", "PackageQuantity", costBasis]
                + selected_net_fields + selected_gross_fields + selected_cost_fields + selected_marginal_fileds
            ))
            result_service = result_service.groupby(
                ["BidNumber", "ServiceCode", "Mode", "TempScenarioNumber"], as_index=False
            )[_ss_sum_cols].sum()
            scee_bid_df['TempScenarioNumber'] = scee_bid_df['TempScenarioNumber'].astype(str)
            result_service['TempScenarioNumber'] = result_service['TempScenarioNumber'].astype(str)
            # Identify any requested scenarios that returned no BigQuery data (not yet rated)
            bq_scenario_numbers = set(result_service['TempScenarioNumber'].unique())
            missing_scenarios = scee_bid_df[
                ~scee_bid_df['TempScenarioNumber'].isin(bq_scenario_numbers)
            ][['ScenarioSystemNumber', 'ScenarioName', 'TempScenarioNumber']].to_dict(orient='records')
            if missing_scenarios:
                log_info("ScenarioSummaryView.get - Some scenarios have no BigQuery data (not yet rated)", context=f"Missing scenarios: {missing_scenarios}", trans_tm=int((time.time() - start_time) * 1000))
            merged_df = pd.merge(
                scee_bid_df[['ScenarioSystemNumber', 'ScenarioName', 'ScenarioNumber', 'TempScenarioNumber']],
                result_service,
                on='TempScenarioNumber',
                how='inner'
            )
            result_service = pd.merge(
                merged_df,
                scenario_bid_details,
                on=['ScenarioSystemNumber', 'BidNumber'],
                how='left'
            )
            result_service.loc[result_service['BidNumber'].astype(str).str.startswith('99'), 'AnalyzerBidName'] = 'Unincented PLD'
            result_service['RevenueAdjustmentValueAmount'] = result_service['RevenueAdjustmentValueAmount'].astype(float).fillna(0.0)
            result_service['PackageQuantity']=result_service['PackageQuantity'].astype(float)
            # result_service['ADV']=result_service['ADV'].round(1)
            result_service['BaseNetReportingAmount']=result_service['BaseNetReportingAmount'].astype(float)
            result_service['BaseGrossReportingAmount']=result_service['BaseGrossReportingAmount'].astype(float)
            result_service[costBasis]=result_service[costBasis].astype(float)
            result_service['NetRevenue'] = result_service['BaseNetReportingAmount'] + result_service[selected_net_fields].sum(axis=1)
            result_service['GrossRevenue'] = result_service['BaseGrossReportingAmount'] + result_service[selected_gross_fields].sum(axis=1)
            result_service['BaseFrt'] = result_service.apply(
                lambda row:
            0.0 if (row['BaseNetReportingAmount']==0 and row['BaseGrossReportingAmount']==0) \
                  else  (100*(1 - 
                ( (row['BaseNetReportingAmount']) / (1 if row['BaseGrossReportingAmount']==0 else row['BaseGrossReportingAmount']) \
                                        ))),axis=1)
            result_service['TotalDisc'] = result_service.apply(
                lambda row:
            0.0 if (row['NetRevenue']==0 and row['GrossRevenue']==0) \
                  else  (100*(1 - 
                ( (row['NetRevenue']) / (1 if row['GrossRevenue']==0 else row['GrossRevenue']) \
                                        ))),axis=1)
                        
            result_service['RPP'] = (result_service['NetRevenue'].div(result_service['PackageQuantity'].replace(0, 1), axis=0 ))
            result_service['AnnualRevenue'] = (result_service['NetRevenue'])
            
            # nedd to check if revenu is same as annaul revenue
            # result_service['AnnualRevenue']=result_service['NetRevenue'].round(2)
            if 'TotalBaseBidFrieghtCost' in costBasis:
                result_service['TotalCost'] = result_service[costBasis] + result_service[selected_cost_fields].sum(axis=1)
                # result_service['TotalCost'] = result_service[costBasis] + result_service[selected_cost_fields].sum(axis=1)
            else:
                result_service['TotalCost'] = result_service[costBasis] + result_service[selected_marginal_fileds].sum(axis=1)
                # result_service['TotalCost'] = result_service[costBasis] + result_service[selected_marginal_fileds].sum(axis=1)
            result_service['OR'] = (result_service['TotalCost'].div(result_service['NetRevenue'].replace(0, 1), axis=0 ))
            result_service['AnnualProfit'] = (result_service['NetRevenue'] - result_service['TotalCost'])
            result_service.rename(columns={
                                    "ServiceCode": "service_code",
                                    "Mode": "service_name"
                                }, inplace=True)
            
            all_fields=selected_cost_fields+selected_gross_fields+selected_marginal_fileds+selected_net_fields
            agg_dict={col: "sum" for col in set(all_fields)}
            agg_dict.update({'ADV': 'sum',
                'BaseNetReportingAmount': 'sum',
                'BaseGrossReportingAmount': 'sum',
                # 'RevenueAdjustmentValueAmount':'sum',
                costBasis: 'sum',
                'PackageQuantity':'sum'})

             
            result_bid=result_service\
            .groupby(['ScenarioSystemNumber','ScenarioNumber','ScenarioName',
                    'BidNumber','AnalyzerBidName','RevenueAdjustmentValueAmount'])\
            .agg(agg_dict)\
            .reset_index()
            
            # result_bid['ADV']=(result_bid['ADV']).round(1)
            result_bid['GrossRevenue'] = result_bid['BaseGrossReportingAmount'] + result_bid[selected_gross_fields].sum(axis=1)
            result_bid['NetRevenue'] = result_bid['BaseNetReportingAmount'] + result_bid[selected_net_fields].sum(axis=1)
            
            result_bid['SubTotalRevenue'] = result_bid['BaseNetReportingAmount'] + result_bid[selected_net_fields].sum(axis=1)+result_bid['RevenueAdjustmentValueAmount']

            result_bid['BaseFrt'] = result_bid.apply(
                lambda row:
            0.0 if (row['BaseNetReportingAmount']==0 and row['BaseGrossReportingAmount']==0) \
                  else  (100*(1 - 
                ( (row['BaseNetReportingAmount']) / (1 if row['BaseGrossReportingAmount']==0 else row['BaseGrossReportingAmount']) \
                                        ))),axis=1)


            result_bid['TotalDisc'] = result_bid.apply(
                lambda row:
            0.0 if (row['NetRevenue']==0 and row['GrossRevenue']==0) \
                  else  (100*(1 - 
                ( (row['NetRevenue']) / (1 if row['GrossRevenue']==0 else row['GrossRevenue']) \
                                        ))),axis=1)
            if 'TotalBaseBidFrieghtCost' in costBasis:
                result_bid['TotalCost'] = result_bid[costBasis] + result_bid[selected_cost_fields].sum(axis=1)
                # result_bid['TotalCost'] = result_bid[costBasis] + result_bid[selected_cost_fields].sum(axis=1)
            else:
                result_bid['TotalCost'] = result_bid[costBasis] + result_bid[selected_marginal_fileds].sum(axis=1)
            
            result_bid['RPP']=(result_bid['NetRevenue'].div(result_bid['PackageQuantity'].replace(0, 1), axis=0 ))
            result_bid['SubTotalRPP']=(result_bid['SubTotalRevenue'].div(result_bid['PackageQuantity'].replace(0, 1), axis=0 ))
            
            result_bid['OR']=(result_bid['TotalCost'].div(result_bid['NetRevenue'].replace(0, 1), axis=0 ))
            result_bid['AnnualProfit']=(result_bid['NetRevenue']-result_bid['TotalCost'])
            result_bid['SubTotalOR']=(result_bid['TotalCost'].div(result_bid['SubTotalRevenue'].replace(0, 1), axis=0 ))
            result_bid['SubTotalAnnualProfit']=(result_bid['SubTotalRevenue']-result_bid['TotalCost'])
            result_bid['AnnualRevenue']=(result_bid['NetRevenue'])
            all_fields=selected_cost_fields+selected_gross_fields+selected_marginal_fileds+selected_net_fields
            agg_dict={col: "sum" for col in set(all_fields)}
            agg_dict.update({'ADV': 'sum',
                'BaseNetReportingAmount': 'sum',
                'BaseGrossReportingAmount': 'sum',
                costBasis: 'sum',
                # 'RevenueAdjustmentValueAmount':'sum',
                'PackageQuantity':'sum'})

            
            result_scenario=result_bid.groupby(['ScenarioSystemNumber','ScenarioNumber','ScenarioName'])\
            .agg(agg_dict)\
            .reset_index()
            
            # result_scenario['ADV']=(result_scenario['ADV']).round(1)
            result_scenario['NetRevenue'] = result_scenario['BaseNetReportingAmount'] +result_scenario[selected_net_fields].sum(axis=1)
            result_scenario['GrossRevenue'] = result_scenario['BaseGrossReportingAmount'] + result_scenario[selected_gross_fields].sum(axis=1)
            result_scenario['BaseFrt'] = result_scenario.apply(
                lambda row:
            0.0 if (row['BaseNetReportingAmount']==0 and row['BaseGrossReportingAmount']==0) \
                  else  (100*(1 - 
                ( (row['BaseNetReportingAmount']) / (1 if row['BaseGrossReportingAmount']==0 else row['BaseGrossReportingAmount']) \
                                        ))),axis=1)


            result_scenario['TotalDisc'] = result_scenario.apply(
                lambda row:
            0.0 if (row['NetRevenue']==0 and row['GrossRevenue']==0) \
                  else  (100*(1 - 
                ( (row['NetRevenue']) / (1 if row['GrossRevenue']==0 else row['GrossRevenue']) \
                                        ))),axis=1)
            if 'TotalBaseBidFrieghtCost' in costBasis:
                result_scenario['TotalCost'] = result_scenario[costBasis] + result_scenario[selected_cost_fields].sum(axis=1)
                # result_scenario['TotalCost'] = result_scenario[costBasis] + result_scenario[selected_cost_fields].sum(axis=1)
            else:
                result_scenario['TotalCost'] = result_scenario[costBasis] + result_scenario[selected_marginal_fileds].sum(axis=1)
                
            result_scenario['AnnualRevenue']=(result_scenario['BaseNetReportingAmount']+result_scenario[selected_net_fields].sum(axis=1))
            result_scenario['RPP']=(result_scenario['AnnualRevenue'].div(result_scenario['PackageQuantity'].replace(0, 1), axis=0 ))
            result_scenario['OR']=(result_scenario['TotalCost'].div(result_scenario['NetRevenue'].replace(0, 1), axis=0 ))
            result_scenario['AnnualProfit']=(result_scenario['NetRevenue']-result_scenario['TotalCost'])
            
            cols_round_2 = ["BaseFrt", "TotalDisc", "RPP", "OR", "AnnualRevenue", "AnnualProfit","SubTotalRPP","SubTotalOR","SubTotalRevenue","SubTotalAnnualProfit"]            
            for df in [result_service, result_bid, result_scenario]:
                for col in cols_round_2:
                    if col in df.columns:
                        df[col] = df[col].apply(lambda x: round(x, 2) if pd.notnull(x) else x)

            def fmt(x, pattern):
                if pattern == "1f":
                    return float(f"{x:.1f}")
                if pattern == "2f":
                    return float(f"{x:.2f}")
                if pattern == "int":
                    return int(x)
                return x
            format_rules = {
                        "1f": ["ADV", "BaseFrt", "TotalDisc"],
                        "2f": ["RPP", "OR","SubTotalRPP","SubTotalOR"],
                        "int": ["AnnualRevenue", "AnnualProfit","SubTotalRevenue","SubTotalAnnualProfit","PackageQuantity"]
                    }
            for df in [result_service, result_bid, result_scenario]:
                for pattern, columns in format_rules.items():
                    for col in columns:
                        if col in df.columns:
                            df[col] = df[col].apply(lambda x: fmt(x, pattern) if pd.notnull(x) else x)  

            
           
            result_service=result_service.astype(str)
            result_bid=result_bid.astype(str)
            result_scenario=result_scenario.astype(str)

            result_service = result_service.replace(['nan', 'NaN', 'None', np.nan], '-')
            result_bid = result_bid.replace(['nan', 'NaN', 'None', np.nan], '-')
            result_scenario = result_scenario.replace(['nan', 'NaN', 'None', np.nan], '-')

            
            for df in [result_service, result_bid, result_scenario]:
                df['BaseFrt'] = df['BaseFrt'].replace('-', '-') + '%'
                df['TotalDisc'] = df['TotalDisc'].replace('-', '-') + '%'
                df['RPP'] = df['RPP'].apply(lambda x: '-'
                                            if x == '-' else f" $ {float(x):,.2f}")
                df['AnnualRevenue'] = df['AnnualRevenue'].apply(lambda x: '-'
                                            if x == '-' else f" $ {int(float(x)):,}")
                df['AnnualProfit'] = df['AnnualProfit'].apply(lambda x: '-'
                                            if x == '-' else f" $ {int(float(x)):,}")
                if 'SubTotalRPP' in df.columns:
                    df['SubTotalRPP'] = df['SubTotalRPP'].apply(lambda x: '-'
                                            if x == '-' else f" $ {float(x):,.2f}")
                if 'SubTotalRevenue' in df.columns:
                    df['SubTotalRevenue'] = df['SubTotalRevenue'].apply(lambda x: '-'
                                            if x == '-' else f" $ {int(float(x)):,}")
                if 'SubTotalAnnualProfit' in df.columns:
                    df['SubTotalAnnualProfit'] = df['SubTotalAnnualProfit'].apply(lambda x: '-'
                                            if x == '-' else f" $ {int(float(x)):,}")
                if 'PackageQuantity' in df.columns:
                    df['PackageQuantity'] = df['PackageQuantity'].apply(lambda x: '-'
                                            if x == '-' else f"{int(float(x)):,}")
            
            final_json=[]
            result_service.rename(columns={'service_code':'name'},inplace=True)
            result_bid.rename(columns={'AnalyzerBidName':'name'},inplace=True)
            json_fields = ["ADV", "BaseFrt", "TotalDisc", "RPP", "AnnualRevenue", "OR", "AnnualProfit", "PackageQuantity"]
            for n1,sce in result_scenario.iterrows():
                data=[]
                total=sce[['ADV','BaseFrt','TotalDisc','RPP','AnnualRevenue',
                            'OR','AnnualProfit','PackageQuantity']].to_dict()
                total['name']='Total'
                data.append(total)
                result_bid_scenario=result_bid[result_bid['ScenarioNumber']==sce['ScenarioNumber']]
                for n2,sbid in result_bid_scenario.iterrows():
                    details=[]
                    details_df=result_service[(result_service['ScenarioNumber']==sbid['ScenarioNumber'])
                        & (result_service['BidNumber']==sbid['BidNumber'])]
                    details_df=details_df.sort_values(by='name')
                    
                    details=details_df[['name','ADV','BaseFrt',
                        'TotalDisc','RPP','AnnualRevenue','OR','AnnualProfit','PackageQuantity']].to_dict(orient='records')
                    is_blank_parent = (
                        len(details) == 1 and
                        details[0]["name"] == "-"  
                    )
                    if is_blank_parent:
                        bid_data = {
                            "name": sbid["name"],
                            **{field: "-" for field in json_fields},
                            "BaseFrt": "-%",
                            "TotalDisc": "-%",
                            "subtotal": subtotal_raw,
                            "details": details
                        }
                        data.append(bid_data)
                        continue

                    bid_data=sbid[['name','ADV','BaseFrt','TotalDisc',
                                  'RPP','AnnualRevenue','OR','AnnualProfit','PackageQuantity']].to_dict()
                    subtotal_raw = {
                        "ADV": '-',
                        "BaseFrt": '-',
                        "TotalDisc": '-',
                        "RPP": sbid['SubTotalRPP'] ,
                        "AnnualRevenue": sbid['SubTotalRevenue'],
                        "OR": sbid['SubTotalOR'],
                        "AnnualProfit": sbid['SubTotalAnnualProfit'],
                        "PackageQuantity": sbid['PackageQuantity']
                    }
                    
                    bid_data['subtotal']=subtotal_raw
                    bid_data['details']=details
                    data.append(bid_data)
                scenario_dict={
                    "scenario": sce['ScenarioName'],
                    "data":data
                }
                final_json.append(scenario_dict)
            log_info("ScenarioSummaryView API completed successfully", context="ScenarioSummaryView.get - API execution completed", trans_tm=int((time.time() - start_time) * 1000))
            if missing_scenarios:
                return Response({"data": final_json, "warnings": [f"The following scenarios have no rated data in BigQuery and were excluded: {[s['ScenarioName'] for s in missing_scenarios]}"]}, status=status.HTTP_200_OK)
            return Response(final_json, status=status.HTTP_200_OK)
        except Exception as e:
            import traceback
            log_error("ScenarioSummaryView API failed", context=f"ScenarioSummaryView.get - Error occurred during API execution", exc=e, trans_tm=int((time.time() - start_time) * 1000))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(azure_token_required,name='dispatch')
class ScenarioComparison(APIView):
    allowed_methods = ['GET']

    def get(self, request):
        start_time = time.time()
        try:
            log_info("API started", context="ScenarioComparison.get - API execution started")
            empId=request.claims['EmpID']
            
            query_start_time = time.time()
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Query executed", context=f"ScenarioComparison.get - Fetching user profile for EmpId {empId}", trans_tm=int((time.time() - query_start_time) * 1000))
            if not user_number:
                log_error("API failed", context=f"ScenarioComparison.get - User not accessible for EmpId {empId}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)
            analyzerpacketsystemnumber = request.GET.get('AnalyzerPacketSystemNumber')
            if not analyzerpacketsystemnumber:
                log_error("API failed", context="ScenarioComparison.get - Analyzer Packet System Number missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing analyzerpacketsystemnumber"}, status=status.HTTP_400_BAD_REQUEST)
            
            scenariosystem_number = request.GET.get('ScenarioSystemNumber')
            if not scenariosystem_number:
                log_error("API failed", context="ScenarioComparison.get - Scenario System Number missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing scenario"}, status=status.HTTP_400_BAD_REQUEST)
            scenariosystemnumber = ast.literal_eval(scenariosystem_number)
            
            costBasis = request.GET.get('CostBasis')
            if not costBasis:
                log_error("API failed", context="ScenarioComparison.get - Cost basis missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing costBasis"}, status=status.HTTP_400_BAD_REQUEST)
            
            revenueBasis = request.GET.get('RevenueBasis')
            if not revenueBasis:
                log_error("API failed", context="ScenarioComparison.get - Revenue basis missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Revenue Basis"}, status=status.HTTP_400_BAD_REQUEST)
            
            # --- Normalize cost basis ---
            if costBasis.strip("'\"") == 'Fully Allocated' or costBasis.strip("'\"") == 'Fully Allocated Cost' :
                costBasis = 'TotalBaseBidFrieghtCost'
                costBasis_field=f"sum({costBasis}) as {costBasis}"
            elif costBasis.strip("'\"") == 'Long Run Marginal' or costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis = 'TotalMarginalFrieghtCost'
                costBasis_field=f"sum({costBasis}) as {costBasis}"
            else:
                log_error("API failed", context=f"ScenarioComparison.get - Invalid Cost Basis {costBasis}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Incorrect Cost Basis"}, status=status.HTTP_400_BAD_REQUEST)
            
            query_start_time = time.time()
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber__in=scenariosystemnumber
                                     ).values(
                        'ScenarioSystemNumber',
                        'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber',
                        'PricingProfileSummarySystemNumber',
                        'PricingProfileSummarySystemNumber__RevenueAdjustmentValueAmount'
                    )
            log_info("Query executed", context="ScenarioComparison.get - Fetching bid info for scenarios", trans_tm=int((time.time() - query_start_time) * 1000))
            
            query_start_time = time.time()
            scee_bid=TScenario.objects.filter(ScenarioSystemNumber__in=scenariosystemnumber).\
                values('ScenarioName','ScenarioSystemNumber','SummaryGeneratedIndicator','ScenarioNumber')
            log_info("Query executed", context="ScenarioComparison.get - Fetching scenario details", trans_tm=int((time.time() - query_start_time) * 1000))
            if not scee_bid:    
                log_error("API failed", context=f"ScenarioComparison.get - No scenario found for scenario system number {scenariosystemnumber}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No scenario found for given scenario system number"}, status=status.HTTP_400_BAD_REQUEST)
            scee_bid_df=pd.DataFrame(scee_bid)
            if not bid_info:
                log_error("API failed", context=f"ScenarioComparison.get - No bid details found for scenario system numbers {scenariosystemnumber}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No bids found for given scenario"}, status=status.HTTP_400_BAD_REQUEST)
            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(columns={
                'ScenarioSystemNumber__ScenarioName': 'ScenarioName',
                'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber',
                'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber',
                'PricingProfileSummarySystemNumber__RevenueAdjustmentValueAmount': 'RevenueAdjustmentValueAmount'
            }, inplace=True)
            # Use each scenario's own ScenarioNumber directly (same as ScenarioSummaryView).
            # getScenarioHierarchy caused scenarios sharing the same parent to resolve to
            # identical ScenarioNumbers → identical BigQuery rows → identical output.
            scee_bid_df['TempScenarioNumber'] = scee_bid_df['ScenarioNumber'].astype(str)
            if bid_df.empty:
                scenario_numbers = []
                bid_numbers = []
            else:
                scenario_numbers = scee_bid_df['TempScenarioNumber'].astype(str).unique()
                bid_numbers = bid_df['BidNumber'].astype(str).unique()
            bidNosList = f"('{bid_numbers[0]}')" if len(bid_numbers) == 1 else "(" + ",".join(f"'{str(b)}'" for b in bid_numbers) + ")"
            scenarioNosList = f"('{scenario_numbers[0]}')" if len(scenario_numbers) == 1 else "(" + ",".join(f"'{str(b)}'" for b in scenario_numbers) + ")"
            REVENUE_FIELD_MAP = {
                                "Fuel Surcharge": {
                                    "net": "FuelSurchargeNetUSD",
                                    "gross": "FuelSurchargeGrossUSD",
                                    "cost": "FuelSurchargeBaseBidCost",
                                    "marginal": "FuelSurchargeMarginalCost"
                                },
                                "Transportation Charges": {
                                    "net": "TransportationChargesNetUSD",
                                    "gross": "TransportationChargesGrossUSD",
                                    "cost": "TransportationChargesBaseBidCost",
                                    "marginal": "TransportationChargesMarginalCost"
                                },
                                "Pickup And Delivery": {
                                    "net": "PickupAndDeliveryNetUSD",
                                    "gross": "PickupAndDeliveryGrossUSD",
                                    "cost": "PickupAndDeliveryBaseBidCost",
                                    "marginal": "PickupAndDeliveryMarginalCost"
                                },
                                "Returns": {
                                    "net": "ReturnsNetUSD",
                                    "gross": "ReturnsGrossUSD",
                                    "cost": "ReturnsBaseBidCost",
                                    "marginal": "ReturnsMarginalCost"
                                },
                                "Other Charges": {
                                    "net": "OtherChargesNetUSD",
                                    "gross": "OtherChargesGrossUSD",
                                    "cost": "OtherChargesBaseBidCost",
                                    "marginal": "OtherChargesMarginalCost"
                                },
                                "Custom Brokerage": {
                                    "net": "CustomBrokerageNetUSD",
                                    "gross": "CustomBrokerageGrossUSD",
                                    "cost": "CustomBrokerageBaseBidCost",
                                    "marginal": "CustomBrokerageMarginalCost"
                                }
                            }

            if revenueBasis in ['All', '"All"',"'All'"]:
                selected_net_fields = [v["net"] for v in REVENUE_FIELD_MAP.values()]
                selected_gross_fields = [v["gross"] for v in REVENUE_FIELD_MAP.values()]
                selected_cost_fields = [v["cost"] for v in REVENUE_FIELD_MAP.values()]
                selected_marginal_fileds=[v["marginal"] for v in REVENUE_FIELD_MAP.values()]
            else:
                try:
                    revenueBasis = ast.literal_eval(revenueBasis)
                except Exception:
                    revenueBasis = [revenueBasis]
                selected_net_fields = [REVENUE_FIELD_MAP[f]["net"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_gross_fields = [REVENUE_FIELD_MAP[f]["gross"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_cost_fields = [REVENUE_FIELD_MAP[f]["cost"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
                selected_marginal_fileds=[REVENUE_FIELD_MAP[f]["marginal"] for f in revenueBasis if f in REVENUE_FIELD_MAP]
            # Build expressions
            net_expr =  ",".join([f"  SUM({col}) as {col}" for col in selected_net_fields])
            gross_expr =  ",".join([f"  SUM({col}) as {col}" for col in selected_gross_fields])
            cost_expr = f",".join([f"  SUM({col}) as {col}" for col in selected_cost_fields])
            marginal_expr=f",".join([f"  SUM({col}) as {col}" for col in selected_marginal_fileds])

            if 'Rebate' in revenueBasis and len(revenueBasis)== 1:
                return Response({"error": "Rebate is not allowed in revenue basis"}, status=status.HTTP_400_BAD_REQUEST)
           
            query=f"""SELECT
                    BidNumber,ScenarioNumber AS TempScenarioNumber,
                    BillToAccountNumber,
                    sum(ADV) as ADV,
                    Sum(BaseNetReportingAmount) AS BaseNetReportingAmount,
                    Sum(BaseGrossReportingAmount) as BaseGrossReportingAmount,
                    {costBasis_field},
                    {cost_expr},
                    {net_expr},
                    {gross_expr},
                    {marginal_expr},
                    Sum(PackageQuantity) as  PackageQuantity,
                    FROM `{shipping_profile_summary}`
                    WHERE AnalyzerPacketID = '{str(analyzerpacketsystemnumber)}'
                    and ScenarioNumber in {scenarioNosList}
                    GROUP BY BidNumber,ScenarioNumber,BillToAccountNumber"""
            
            query_start_time = time.time()
            query_job = client.query(query)
            result_rows = query_job.result()
            result_data = [dict(row.items()) for row in result_rows]
            result_df = pd.DataFrame(result_data)
            log_info("BigQuery executed", context="ScenarioComparison.get - Fetching scenario comparison data from BigQuery", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if result_df.empty:
                log_info("API completed", context="ScenarioComparison.get - No data found for selected scenarios", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data found for the selected scenarios"}, status=status.HTTP_200_OK)
            # Per-row AF: handles mixed HPLD/OPLD accounts before aggregation
            result_df['PackageQuantity'] = result_df['PackageQuantity'].astype(float)
            result_df["_af"] = result_df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(analyzerpacketsystemnumber, account_number=str(acct))
            )
            result_df["PackageQuantity"] = result_df["PackageQuantity"] * result_df["_af"]
            result_df.drop(columns=["_af", "BillToAccountNumber"], inplace=True)
            _sc_sum_cols = list(dict.fromkeys(
                ["ADV", "BaseNetReportingAmount", "BaseGrossReportingAmount", "PackageQuantity", costBasis]
                + selected_net_fields + selected_gross_fields + selected_cost_fields + selected_marginal_fileds
            ))
            result_df = result_df.groupby(["BidNumber", "TempScenarioNumber"], as_index=False)[_sc_sum_cols].sum()
            scee_bid_df['TempScenarioNumber']=scee_bid_df['TempScenarioNumber'].astype(str)
            merged_df = pd.merge(scee_bid_df[[ 'ScenarioSystemNumber', 'ScenarioName','ScenarioNumber','TempScenarioNumber']], 
                                 result_df,on=['TempScenarioNumber'], how='inner')
            merged_df = pd.merge(merged_df, bid_df, on=['ScenarioSystemNumber','BidNumber'], how='left')
            merged_df['RevenueAdjustmentValueAmount'] = merged_df['RevenueAdjustmentValueAmount'].astype(float).fillna(0)
            
            agg_dict={
                "ADV": 'sum',
                'BaseNetReportingAmount': 'sum',
                'BaseGrossReportingAmount': 'sum',
                'PackageQuantity': 'sum',
                'RevenueAdjustmentValueAmount':'sum',
                costBasis:'sum'
            }
            
            for col in selected_net_fields + selected_gross_fields + selected_cost_fields + selected_marginal_fileds:
                if col in merged_df.columns:
                    agg_dict[col] = 'sum'
            grouped = merged_df.groupby(['ScenarioSystemNumber','ScenarioName']).agg(agg_dict).reset_index()
            grouped['NetRevenue'] = grouped['BaseNetReportingAmount'] + grouped[selected_net_fields].sum(axis=1)
            grouped['GrossRevenue'] = grouped['BaseGrossReportingAmount'] + grouped[selected_gross_fields].sum(axis=1)
            grouped['BaseFrtDisc'] = 1 - (grouped['BaseNetReportingAmount'] / grouped['BaseGrossReportingAmount'])
            grouped['NetRevenue'] = grouped['NetRevenue'] + grouped['RevenueAdjustmentValueAmount']
            grouped['TotalDisc'] = 1 - (grouped['NetRevenue'] / grouped['GrossRevenue'])
            grouped['RPP'] = grouped['NetRevenue'] / grouped['PackageQuantity'].replace(0, 1)
            if 'TotalBaseBidFrieghtCost' in costBasis:
                grouped['TotalCost'] = grouped[costBasis] + grouped[selected_cost_fields].sum(axis=1)

            else:
                grouped['TotalCost'] = grouped[costBasis] + grouped[selected_marginal_fileds].sum(axis=1)
            grouped['OR'] = grouped['TotalCost'] / grouped['NetRevenue']
            grouped['Profit'] = grouped['NetRevenue'] - grouped['TotalCost']

            output = []
            for _, row in grouped.iterrows():
                output.append({
                    "ScenarioName": row.get("ScenarioName", ""),
                    "adv": f"{row['ADV']:.1f}",
                    "BaseFrtDisc": f"{row['BaseFrtDisc'] * 100:.1f}%",
                    "TotalDisc": f"{row['TotalDisc'] * 100:.1f}%",
                    "RPP": f"$ {row['RPP']:.2f}",
                    "Revenue": f"$ {int(row['NetRevenue']):,}",
                    "OR": f"{row['OR']:.2f}" if row['OR'] is not None else None,
                    "Profit": f"$ {int(row['Profit']):,}" if row['Profit'] is not None else None
                })
            if len(grouped) >= 2:
                numeric_cols = grouped.select_dtypes(include='number').columns
                diff = grouped.iloc[1][numeric_cols] - grouped.iloc[0][numeric_cols]

                output.append({
                    "adv": f"{diff['ADV']:.1f}",
                    "BaseFrtDisc": f"{diff['BaseFrtDisc'] * 100:.1f}%",
                    "TotalDisc": f"{diff['TotalDisc'] * 100:.1f}%",
                    "RPP": f"$ {diff['RPP']:.2f}",
                    "Revenue": f"$ {int(diff['NetRevenue']):,}",
                    "OR": f"{diff.get('OR', 0):.2f}" if pd.notnull(diff.get('OR')) else None,
                    "Profit": f"$ {int(diff.get('Profit', 0)):,}" if pd.notnull(diff.get('Profit')) else None
                })
            log_info("API completed successfully", context="ScenarioComparison.get - API execution completed", trans_tm=int((time.time() - start_time) * 1000))
            return Response(output, status=status.HTTP_200_OK)
        except Exception as e:
            log_error("API failed", context="ScenarioComparison.get - Error during API execution", exc=e, trans_tm=int((time.time() - start_time) * 1000))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)



@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileFilters(APIView):
    allowed_methods = ['GET']

    def get(self, request):
        start_time = time.time()
        try:
            log_info("API started", context="ShippingProfileFilters.get - API execution started")
            
            query_start_time = time.time()
            user_number = TUserProfile.objects.filter(CloudUserIdentificationNumber=request.claims['EmpID'])
            log_info("Query executed", context="ShippingProfileFilters.get - Fetching user profile for authentication", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not user_number:
                log_error("API failed", context="ShippingProfileFilters.get - User not accessible", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)

            analyzer_packet_system_number = request.GET.get('AnalyzerPacketSystemNumber')
            if not analyzer_packet_system_number:
                log_error("API failed", context="ShippingProfileFilters.get - Analyzer Packet System Number missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing AnalyzerPacketSystemNumber"}, status=status.HTTP_400_BAD_REQUEST)

            query_start_time = time.time()
            scenarios=TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber__AnalyzerPacketSystemNumber=analyzer_packet_system_number).values(
                    'ScenarioSystemNumber','ScenarioSystemNumber__ScenarioName',
                    'ScenarioSystemNumber__ScenarioNumber',
                    'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber',
                    'ScenarioSystemNumber__SummaryGeneratedIndicator')
            log_info("Query executed", context="ShippingProfileFilters.get - Fetching scenarios for analyzer packet", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not scenarios:
                log_error("API failed", context=f"ShippingProfileFilters.get - No scenarios found for analyzer packet {analyzer_packet_system_number}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': 'scenarioNames not found in ShippingProfileFilters'}, status=status.HTTP_404_NOT_FOUND)

            scenario_df=pd.DataFrame(scenarios)
            scenario_df.rename(columns={
                'ScenarioSystemNumber__ScenarioName': 'Name',
                'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber',
                'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator'
            }, inplace=True)
            
            scenario_df['ScenarioNumber']=scenario_df.apply(
                lambda x: getScenarioHierarchy(x['ScenarioSystemNumber']) if x['SummaryGeneratedIndicator'] == False else str(x['ScenarioNumber']), axis=1)
            scenario_df['ScenarioNumber']=scenario_df['ScenarioNumber'].apply(str)
            scenario_list= scenario_df['ScenarioNumber'].unique().tolist()
            scenario_list = f"('{scenario_list[0]}')" if len(scenario_list) == 1 else tuple(scenario_list)
            bid_list= scenario_df['BidNumber'].unique().tolist()
            bid_list = f"('{bid_list[0]}')" if len(bid_list) == 1 else tuple(bid_list)

            query=f"""
                WITH account_services AS (
                    SELECT ScenarioNumber, BidNumber, BillToAccountNumber AS AccountNumber,
                    ARRAY_AGG(DISTINCT ServiceCode ORDER BY ServiceCode) AS ServiceCode
                    FROM {shipping_profile_summary}
                    WHERE AnalyzerPacketID = '{analyzer_packet_system_number}'
                    AND ScenarioNumber IN {scenario_list}
                    AND BidNumber IN {bid_list}
                    GROUP BY ScenarioNumber, BidNumber, BillToAccountNumber
                    )

                    SELECT ScenarioNumber, BidNumber,
                    ARRAY_AGG( STRUCT( AccountNumber, ServiceCode )
                    ORDER BY AccountNumber ) AS BilltoAccount
                    FROM account_services
                    GROUP BY ScenarioNumber, BidNumber;
                """
            
            query_start_time = time.time()
            result = client.query(query).to_dataframe()
            log_info("BigQuery executed", context="ShippingProfileFilters.get - Fetching account and service details from BigQuery", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if result.empty:
                log_error("API failed", context=f"ShippingProfileFilters.get - No data found for analyzer packet {analyzer_packet_system_number}", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': 'No data found in ShippingProfileFilters'}, status=status.HTTP_404_NOT_FOUND)

            result=scenario_df.merge(result,on=['ScenarioNumber','BidNumber'],how='left')
            for row in result.loc[result.BilltoAccount.isnull(), 'BilltoAccount'].index:
                result.at[row, 'BilltoAccount'] = [{"AccountNumber": "", "ServiceCode": []}]
            
            result=result.groupby(['ScenarioSystemNumber','Name','ScenarioNumber'])\
                .apply(lambda x: x[['BidNumber','BilltoAccount']].to_dict(orient='records'))\
                .reset_index(name='Bid')
            
            result=result.to_dict(orient='records')
            log_info("API completed successfully", context="ShippingProfileFilters.get - API execution completed", trans_tm=int((time.time() - start_time) * 1000))
            return Response({"Scenario": result}, status=status.HTTP_200_OK)

        except Exception as e:
            log_error("API failed", context="ShippingProfileFilters.get - Error during API execution", exc=e, trans_tm=int((time.time() - start_time) * 1000))
            return Response({"error": f"Invalid user {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileSummaryWeightAPIView(APIView):
    allowed_methods = ["GET"]
    def get(self, request):
        start_time = time.time()
        try:
            log_info("API started", context="ShippingProfileSummaryWeightAPIView.get - API execution started")
            
            query_start_time = time.time()
            user_number = TUserProfile.objects.filter(CloudUserIdentificationNumber=request.claims['EmpID'])
            log_info("Query executed", context="ShippingProfileSummaryWeightAPIView.get - Fetching user profile for authentication", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not user_number:
                log_error("API failed", context="ShippingProfileSummaryWeightAPIView.get - User not accessible", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)

            analyzer_id = request.query_params.get("analyzer_id")
            scenario_system_number = request.query_params.get("scenario_system_number")
            bid_number = request.query_params.get("bid_number", "all")
            acc_nums = request.query_params.get("accounts", "all")
            svc_codes = request.query_params.get("service", "all")
            costBasis = request.query_params.get("costBasis")
            servicefeaturetypecode=request.query_params.get("servicefeaturetypecode","all")
            if not servicefeaturetypecode:
                log_error("API failed", context="ShippingProfileSummaryWeightAPIView.get - Service Feature Type Code missing", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing servicefeaturetypecode"}, status=status.HTTP_400_BAD_REQUEST)
            if not analyzer_id or not scenario_system_number:
                log_error("API failed", context="ShippingProfileSummaryWeightAPIView.get - Missing analyzer_id or scenario_system_number", trans_tm=int((time.time() - start_time) * 1000))
                return Response(
                    {"message": "Missing required parameters: analyzer_id or scenario_system_number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            query_start_time = time.time()
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber=scenario_system_number
            ).values(
                "ScenarioSystemNumber",
                "ScenarioSystemNumber__ScenarioNumber",
                "ScenarioSystemNumber__SummaryGeneratedIndicator",
                "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber",
            )
            log_info("Query executed", context="ShippingProfileSummaryWeightAPIView.get - Fetching bid info for scenario", trans_tm=int((time.time() - query_start_time) * 1000))
            if not bid_info:
                log_info("Shipping Profile Summary Weight API GET Method", context=f"No bids found for scenario system number: {scenario_system_number}")
                log_info("Shipping Profile Summary Weight API GET Method", context="Shipping Profile Summary Weight API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No bids found"}, status=status.HTTP_400_BAD_REQUEST)

            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(
                columns={
                    "ScenarioSystemNumber__ScenarioNumber": "ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator": "SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber": "BidNumber",
                },
                inplace=True,
            )
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            if bid_number.lower() == "all":
                bid_list = bid_df["BidNumber"].dropna().unique().tolist()
            else:
                bid_list = bid_number.split(",")

            # --- Step 3: Adjust ScenarioNumber based on SummaryGeneratedIndicator ---
            bid_df["ScenarioNumber"] = bid_df.apply(
                lambda r: getScenarioHierarchy(r["ScenarioSystemNumber"])  if not r["SummaryGeneratedIndicator"] else str(r["ScenarioNumber"]),
                axis=1,
            )
            scenario_number=bid_df['ScenarioNumber'].unique()[0]
            bid_param = ",".join([f"'{b}'" for b in bid_list])
            account_filter = ""
            service_filter = ""
            servicefeaturetypecode_filter=""
            servicefeaturetypecode=servicefeaturetypecode.strip("'\"")
            acc_nums = acc_nums.split(",") if acc_nums.lower() != "all" else ["All"]
            svc_codes = svc_codes.split(",") if svc_codes.lower() != "all" else ["All"]
            servicefeaturetypecode_list=servicefeaturetypecode.split(",") if servicefeaturetypecode.lower()!="all" else ["All"]

            account_filter = " AND BillToAccountNumber IN (" + ",".join(f'"{x}"' for x in acc_nums) + ")" if "All" not in acc_nums else ""
            service_filter = " AND ServiceCode IN (" + ",".join(f'"{x}"' for x in svc_codes) + ")" if "All" not in svc_codes else ""
            servicefeaturetypecode_filter = " AND ServiceFeatureTypeCode IN (" + ",".join(f'"{x}"' for x in servicefeaturetypecode_list) + ")" if "All" not in servicefeaturetypecode_list else ""
            # --- 2. Validate Cost Basis ---
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='TotalBaseBidFrieghtCost'
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='TotalMarginalFrieghtCost'
            else:
                raise Exception(f"Incorrect Cost Basis")

            # --- 3. Build BigQuery query ---
            project_id = os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table = os.getenv("TABLE_SUMMARY_SHIPPING_PROFILE")
            # ------
            query = f"""
                SELECT
                  BidNumber,
                  BillToAccountNumber,
                  MovementDirectionCode,
                  Mode,
                  ServiceCode,
                  COALESCE(NULLIF(TRIM(ServiceGroup), ""), CONCAT(ServiceCode," - ",ContainerCode)) AS ServiceGroup,
                  BillableWeight,
                  COUNT(*) AS WeightCount,
                  SUM(PackageQuantity) AS Volume,
                  SUM(BaseGrossReportingAmount) AS BaseGrossReportingAmount,
                  SUM(ADV) AS ADV,
                  SUM(BillableWeight*PackageQuantity)/IF(SUM(PackageQuantity)=0,1,SUM(PackageQuantity)) AS WeightPerPice,
                  (SUM(BaseGrossReportingAmount) - SUM(BaseNetReportingAmount)) * 100 / IF(SUM(BaseGrossReportingAmount) = 0, 1, SUM(BaseGrossReportingAmount))  AS FreightDisc,
                  SUM(BaseNetReportingAmount) / IF(SUM(PackageQuantity) = 0, 1, SUM(PackageQuantity)) AS FreightRPP,
                  SUM(BaseNetReportingAmount) AS FreightNetSpent,
                  SUM(BaseGrossReportingAmount) AS FreightGrossSpent,
                  SUM(BaseNetReportingAmount) AS BaseNetReportingAmount,
                  SUM(TotalBaseBidFrieghtCost) AS TotalBaseBidFrieghtCost,
                  SUM(TotalMarginalFrieghtCost) AS TotalMarginalFrieghtCost,
                  SUM(PackageQuantity) AS PackageQuantity,
                  SUM(TotalShipments) AS TotalShipments
                  FROM `{project_id}.{dataset}.{table}`
                  WHERE AnalyzerPacketID = '{analyzer_id}' and ScenarioNumber = '{scenario_number}'
                  AND BidNumber IN ({bid_param})
                  {account_filter}
                  {servicefeaturetypecode_filter}
                  {service_filter}
                GROUP BY
                  BidNumber, BillToAccountNumber, MovementDirectionCode, Mode, ServiceCode, BillableWeight, ServiceGroup
            """
            
            query_start_time = time.time()
            result = client.query(query).result()
            result_data = [dict(row) for row in result]
            log_info("BigQuery executed", context="ShippingProfileSummaryWeightAPIView.get - Fetching weight summary data from BigQuery", trans_tm=int((time.time() - query_start_time) * 1000))
            
            if not result_data:
                log_info("API completed", context="ShippingProfileSummaryWeightAPIView.get - No data found for provided filters", trans_tm=int((time.time() - start_time) * 1000))
                return Response(
                    {"message": "No data for provided inputs"},
                    status=status.HTTP_200_OK,
                )
            df = pd.DataFrame(result_data)

            # Ensure BillableWeight exists and is numeric
            if "BillableWeight" not in df.columns:
                raise ValueError("BillableWeight column missing from BigQuery result.")
            # After: df = pd.DataFrame(result_data)
            df["BillableWeight"] = pd.to_numeric(df["BillableWeight"], errors="coerce").fillna(0)
            df = df.sort_values(by="BillableWeight",na_position='last')

            # Apply per-row AF BEFORE re-aggregating to correctly handle mixed HPLD/OPLD data.
            df["_af"] = df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(analyzer_id, account_number=str(acct))
            )
            df["_orig_pq"] = df["PackageQuantity"]          # raw PQ, needed for WeightPerPice
            df["PackageQuantity"] = df["PackageQuantity"] * df["_af"]
            df["Volume"] = df["Volume"] * df["_af"]
            # Re-aggregate to original dimensions (drop BillToAccountNumber)
            _w_grp = ["BidNumber", "MovementDirectionCode", "Mode", "ServiceCode", "BillableWeight"]
            _w_sums = ["WeightCount", "Volume", "BaseGrossReportingAmount", "ADV",
                       "BaseNetReportingAmount", "TotalBaseBidFrieghtCost",
                       "TotalMarginalFrieghtCost", "PackageQuantity", "_orig_pq", "TotalShipments"]
            df = df.groupby(_w_grp, as_index=False)[_w_sums].sum()
            df["WeightPerPice"] = df["BillableWeight"]
            df = df.sort_values(by="BillableWeight", na_position="last")
            annualization_factor = 1.0  # already applied per-row above


            # --- 4. Aggregation formulas ---
            costBasis = costBasis.strip().lower()

            if costBasis == "totalbasebidfrieghtcost":
                df["FreightProfit"] = df["BaseNetReportingAmount"] - df["TotalBaseBidFrieghtCost"]
                df["FreightOR"] = (df["TotalBaseBidFrieghtCost"] / df["BaseNetReportingAmount"]).where(
                    df["BaseNetReportingAmount"] != 0, 0
                )
            elif costBasis == "totalmarginalfrieghtcost":
                df["FreightProfit"] = df["BaseNetReportingAmount"] - df["TotalMarginalFrieghtCost"]
                df["FreightOR"] = (df["TotalMarginalFrieghtCost"] / df["BaseNetReportingAmount"]).where(
                    df["BaseNetReportingAmount"] != 0, 0
                )
            else:
                return Response(
                    {"message": "Invalid costBasis. Use 'FullyAllocatedCost' or 'LongRunMarginalCost'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            def safe(v):
                """Convert any numeric expression into a JSON‑safe float."""
                try:
                    v = float(v)
                    if math.isnan(v) or math.isinf(v):
                        return 0.0
                    return v
                except:
                    return 0.0
            service_map = dict(
                TServiceHierarchy.objects
                .values_list(
                    "PricingCoreServiceCode",
                    "PricingCoreServiceCodeDescriptionText"
                )
            )

            df["Service"] = df["ServiceCode"].map(service_map).fillna(df["ServiceCode"])
            # --- 5. Group by ServiceCode & prepare output ---
            response_data = []
            log_info(
                "Preparing response payload",
                context="ShippingProfileSummaryWeightAPIView.get - Aggregating service data"
            )
            for service_code, service_group in df.groupby("ServiceCode"):
                pkg_sum = safe(service_group["PackageQuantity"].sum())
                base_net_sum = safe(service_group["BaseNetReportingAmount"].sum())
                # Compute total weight by summing the product across the group
                total_weight = safe((service_group["BillableWeight"] * service_group["WeightCount"]).sum())
                total_volume = int(round(safe(service_group["Volume"].sum())))
                adv = safe(service_group["ADV"].sum())
                pps = safe(pkg_sum / safe(service_group["TotalShipments"].sum()) if safe(service_group["TotalShipments"].sum()) != 0 else 0)

                weight_piece = safe((service_group["WeightPerPice"] * service_group["_orig_pq"]).sum() / max(service_group["_orig_pq"].sum(), 1e-9))

                freight_gross = safe(service_group["BaseGrossReportingAmount"].sum())
                freight_net = safe(service_group["BaseNetReportingAmount"].sum())
                freight_disc = \
                    safe(((service_group["BaseGrossReportingAmount"].sum() - service_group["BaseNetReportingAmount"].sum())
                    * 100) / service_group["BaseGrossReportingAmount"].sum() if service_group["BaseGrossReportingAmount"].sum() != 0 else 0)
                freight_rpp = \
                    safe(service_group["BaseNetReportingAmount"].sum() / pkg_sum if pkg_sum != 0 else 0)
                if costBasis == "totalbasebidfrieghtcost":
                    freight_profit = safe(service_group["BaseNetReportingAmount"].sum() - service_group["TotalBaseBidFrieghtCost"].sum())
                    freight_or = safe(service_group["TotalBaseBidFrieghtCost"].sum() / service_group["BaseNetReportingAmount"].sum() if base_net_sum != 0 else 0)
                else:
                    freight_profit = safe(service_group["BaseNetReportingAmount"].sum() - service_group["TotalMarginalFrieghtCost"].sum())
                    freight_or = safe(service_group["TotalMarginalFrieghtCost"].sum() / service_group["BaseNetReportingAmount"].sum() if base_net_sum != 0 else 0)
                # --- Build details per BillableWeight ---
                details = []
                grouped_details = service_group.groupby("BillableWeight", as_index=False)

                for weight, detail_group in grouped_details:
                    detail_pkg_sum = detail_group["PackageQuantity"].sum()
                    base_net_sum_d = detail_group["BaseNetReportingAmount"].sum()
                    details.append({
                        "Movement": detail_group["MovementDirectionCode"].iloc[0],
                        "ServiceGroup": service_group,
                        "Mode": detail_group["Mode"].iloc[0],
                        "name": service_code,
                        "Weight": float(f"{(detail_group['BillableWeight']).sum():.2f}"),
                        "Volume": int(round(detail_group["Volume"].sum())),
                        "ADV": float(f"{detail_group['ADV'].sum():.1f}"),
                        "PPS": float(f"{((detail_group['PackageQuantity']).sum() / detail_group['TotalShipments'].sum()) if detail_group['TotalShipments'].sum() != 0 else 0:.2f}"),

                        "WeightPiece": float(f"{(detail_group['WeightPerPice'] * detail_group['_orig_pq']).sum() / max(detail_group['_orig_pq'].sum(), 1e-9):.2f}"),

                        "FreightGross": f"$ {float(detail_group['BaseGrossReportingAmount'].sum()):,.2f}",
                        "FreightDiscount": f"{float(((detail_group['BaseGrossReportingAmount'].sum() - detail_group['BaseNetReportingAmount'].sum())* 100) / detail_group['BaseGrossReportingAmount'].sum() if detail_group['BaseGrossReportingAmount'].sum() != 0 else 0):.2f}%",
                        "FreightRPP": f"$ {float(detail_group['BaseNetReportingAmount'].sum() / detail_pkg_sum if detail_pkg_sum != 0 else 0):.2f}",
                        "FreightNet": f"$ {float(detail_group['BaseNetReportingAmount'].sum()):,.2f}",
                        "FreightProfit": f"$ {float(detail_group['BaseNetReportingAmount'].sum() - (detail_group['TotalBaseBidFrieghtCost'].sum() if costBasis == 'totalbasebidfrieghtcost' else detail_group['TotalMarginalFrieghtCost'].sum())):,.2f}",
                        "FreightOR": f"{float((detail_group['TotalBaseBidFrieghtCost'].sum() / base_net_sum_d if costBasis == 'totalbasebidfrieghtcost' and base_net_sum_d != 0 else detail_group['TotalMarginalFrieghtCost'].sum() / base_net_sum_d if costBasis == 'totalmarginalfrieghtcost' and base_net_sum_d != 0 else 0)):.2f}",
                    })

                response_data.append({
                    "Movement": service_group["MovementDirectionCode"].iloc[0],
                    "Mode": service_group["Mode"].iloc[0],
                    "name": service_code,
                    "Weight": "-",
                    "ServiceCode": service_code,
                    "Service": service_group["Service"].iloc[0],
                    "Volume": total_volume,
                    "ADV": float(f"{adv:.1f}"),
                    "PPS": float(f"{pps:.2f}"),
                    "WeightPiece": float(f"{weight_piece:.2f}"),
                    "FreightGross": f"$ {freight_gross:,.2f}",
                    "FreightDiscount": f"{freight_disc:.2f}%",
                    "FreightRPP": f"$ {freight_rpp:,.2f}",
                    "FreightNet": f"$ {freight_net:,.2f}",
                    "FreightProfit": f"$ {freight_profit:,.2f}",
                    "FreightOR": f"{freight_or:.2f}",
                    "details": details
                })

            
            # --- 6. Final response ---
            log_info("API completed successfully", context="ShippingProfileSummaryWeightAPIView.get - API execution completed", trans_tm=int((time.time() - start_time) * 1000))
            return Response([{"data": response_data}], status=status.HTTP_200_OK)

        except Exception as e:
            log_error("API failed", context="ShippingProfileSummaryWeightAPIView.get - Error during API execution", exc=e, trans_tm=int((time.time() - start_time) * 1000))
            return Response(
                {"error": f"Something went wrong: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileSummaryZoneAPIView_V1(APIView):
    allowed_methods = ["GET"]

    def get(self, request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Started")
            user_number = TUserProfile.objects.filter(CloudUserIdentificationNumber=request.claims['EmpID'])
            log_info("Shipping Profile Summary Zone API GET Method", context=f"User Authentication : {request.claims['EmpID']}")
            log_debug("Shipping Profile Summary Zone API GET Method", context=f"Query : {str(user_number.query)}")
            if not user_number:
                log_error("Shipping Profile Summary Zone API GET Method", context=f"Not accessible. Emp Id:{request.claims['EmpID']}")
                log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)

            analyzer_id = request.query_params.get("analyzer_id")
            scenario_system_number = request.query_params.get("scenario_system_number")
            bid_number = request.query_params.get("bid_number", "all")
            acc_nums = request.query_params.get("accounts", "all")
            service_codes = request.query_params.get("service", "all")
            zone_list = request.query_params.get("zone")
            costBasis = request.query_params.get("costBasis")  
            servicefeaturetypecode=request.query_params.get("servicefeaturetypecode","all")
            if not servicefeaturetypecode:
                log_error("Shipping Profile Summary Zone API GET Method", context=f"Service Feature Type Code missing")
                log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing servicefeaturetypecode"}, status=status.HTTP_400_BAD_REQUEST)
            # --- Validate required parameters ---
            if not analyzer_id or not scenario_system_number:
                log_error("Shipping Profile Summary Zone API GET Method", context=f"Missing required parameters: analyzer_id or scenario_system_number")
                log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "Missing required parameters: analyzer_id or scenario_system_number"}, status=status.HTTP_200_OK)

            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber=scenario_system_number
            ).values(
                "ScenarioSystemNumber",
                "ScenarioSystemNumber__ScenarioNumber",
                "ScenarioSystemNumber__SummaryGeneratedIndicator",
                "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber",
            )
            log_debug("Shipping Profile Summary Zone API GET Method", context=f"Query : {str(bid_info.query)}")
            if not bid_info:
                log_error("Shipping Profile Summary Zone API GET Method", context=f"No bids found for scenario system number: {scenario_system_number}")
                log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No bids found"}, status=status.HTTP_400_BAD_REQUEST)

            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(
                columns={
                    "ScenarioSystemNumber__ScenarioNumber": "ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator": "SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber": "BidNumber",
                },
                inplace=True,
            )
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            if bid_number.lower() == "all":
                bid_list = bid_df["BidNumber"].dropna().unique().tolist()
            else:
                bid_list = bid_number.split(",")

            # --- Step 3: Adjust ScenarioNumber based on SummaryGeneratedIndicator ---
            bid_df["ScenarioNumber"] = bid_df.apply(
                lambda r: getScenarioHierarchy(r["ScenarioSystemNumber"]) if not r["SummaryGeneratedIndicator"] else str(r["ScenarioNumber"]),
                axis=1,
            )
            scenario_number=bid_df['ScenarioNumber'].unique()[0]
            servicefeaturetypecode=servicefeaturetypecode.strip("'\"")
            bid_param = ",".join([f"'{b}'" for b in bid_list])
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            acc_nums = acc_nums.split(",") if acc_nums.lower() != "all" else ["All"]
            service_codes = service_codes.split(",") if service_codes.lower() != "all" else ["All"]
            zone_list = zone_list.split(",") if zone_list and zone_list.lower() != "all" else ["All"]
            servicefeaturetypecode_list=servicefeaturetypecode.split(",") if servicefeaturetypecode.lower()!="all" else ["All"]
            
            account_filter = " AND BillToAccountNumber IN (" + ",".join(f'"{x}"' for x in acc_nums) + ")" if "All" not in acc_nums else ""
            service_filter = " AND ServiceCode IN (" + ",".join(f'"{x}"' for x in service_codes) + ")" if "All" not in service_codes else ""
            zone_filter = " AND DeliveryZoneNumber IN (" + ",".join(f'"{x}"' for x in zone_list) + ")" if "All" not in zone_list else ""
            servicefeaturetypecode_filter = " AND ServiceFeatureTypeCode IN (" + ",".join(f'"{x}"' for x in servicefeaturetypecode_list) + ")" if "All" not in servicefeaturetypecode_list else ""
            
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='TotalBaseBidFrieghtCost'
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='TotalMarginalFrieghtCost'
            else:
                raise Exception(f"Incorrect Cost Basis")
            # --- Step 5: Build BigQuery query ---
            project_id =  os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table = os.getenv("TABLE_SUMMARY_SHIPPING_PROFILE")
            query = f"""
                SELECT
                    BidNumber,
                    ServiceCode,
                    COALESCE(NULLIF(TRIM(ServiceGroup), ""), CONCAT(ServiceCode," - ",ContainerCode)) AS ServiceGroup,
                    DeliveryZoneNumber AS zone,
                    BillToAccountNumber,
                    MovementDirectionCode,
                    Mode,
                    Lane,
                    SUM(PackageQuantity) AS Volume,
                    SUM(BaseGrossReportingAmount) AS BaseGrossReportingAmount,
                    SUM(ADV) AS ADV,
                    SUM(PackageQuantity)/IF(SUM(TotalShipments)=0,1,SUM(TotalShipments)) AS PPS,
                    SAFE_DIVIDE(SUM(BillableWeight*PackageQuantity), NULLIF(SUM(PackageQuantity), 0)) AS WeightPerPice,
                    SUM(BaseGrossReportingAmount) AS FreightGross,
                    (SUM(BaseGrossReportingAmount) - SUM(BaseNetReportingAmount)) * 100 / IF(SUM(BaseGrossReportingAmount)=0,1,SUM(BaseGrossReportingAmount)) AS FreightDiscount,
                    SUM(BaseNetReportingAmount) / IF(SUM(PackageQuantity) = 0, 1, SUM(PackageQuantity)) AS FreightRPP,
                    SUM(BaseNetReportingAmount) AS FreightNet,
                    SUM(BaseNetReportingAmount) AS BaseNetReportingAmount,
                    SUM({costBasis}) AS CostBasis,
                    SUM(PackageQuantity) AS PackageQuantity,
                    SUM(TotalShipments) AS TotalShipments
                    FROM `{project_id}.{dataset}.{table}`
                WHERE AnalyzerPacketID = '{analyzer_id}' and ScenarioNumber = '{scenario_number}'
                AND BidNumber IN ({bid_param})
                {account_filter}
                {servicefeaturetypecode_filter}
                {service_filter}
                {zone_filter}
                GROUP BY
                    BidNumber, ServiceCode, BillToAccountNumber, DeliveryZoneNumber, MovementDirectionCode, Mode, Lane, ServiceGroup
                ORDER BY ServiceCode, zone, ServiceGroup            """
            log_debug("Shipping Profile Summary Zone API GET Method", context=f"BigQuery : {query}")
            client = bigquery.Client(project=project_id)
            result = client.query(query).result()
            result_data = [dict(row) for row in result]
            if not result_data:
                log_info("Shipping Profile Summary Zone API GET Method", context=f"No data found for the provided filters from BigQuery")
                log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data for provided inputs"}, status=status.HTTP_200_OK)
            log_info(
                "Fetched BigQuery results",
                context="ShippingProfileSummaryZoneAPIView_V1.get - BigQuery result set ready"
            )
            df = pd.DataFrame(result_data)
            numbered_columns=['Volume','BaseGrossReportingAmount','ADV','PPS','WeightPerPice',
                              'FreightGross','FreightDiscount','FreightRPP','FreightNet','BaseNetReportingAmount',
                              'CostBasis','PackageQuantity','TotalShipments']
            df[numbered_columns]=df[numbered_columns].fillna(0)
            if "PackageQuantity" not in df.columns or df["PackageQuantity"].sum() == 0:
                df["PackageQuantity"] = 1
            response_data = []
            log_info(
                "Calculating response aggregates",
                context="ShippingProfileSummaryZoneAPIView_V1.get - Aggregating zone-level metrics"
            )
            if "zone" in df.columns:
                df["zone"] = pd.to_numeric(df["zone"], errors="coerce")
                df = df.sort_values("zone", na_position="last")

            # Apply annualization factor per account to correctly handle mixed HPLD/OPLD data.
            df["_af"] = df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(analyzer_id, account_number=str(acct))
            )
            df["_orig_pq"] = df["PackageQuantity"]
            df["PackageQuantity"] = df["PackageQuantity"] * df["_af"]
            df["Volume"] = df["Volume"] * df["_af"]

            def safe_div(n, d):
                return n / d if d not in (0, None) else 0

            grouped = df.groupby("ServiceCode")
            for service_code, group in grouped:
                # Zone-level details — aggregate across bids/accounts so each zone appears once
                details = []
                for (zone_val, service_group), zone_group in group.groupby(
                    ["zone", "ServiceGroup"], sort=False
                ):
                    zone_pkg    = zone_group["PackageQuantity"].sum()
                    zone_ships  = zone_group["TotalShipments"].sum()
                    zone_vol    = zone_group["Volume"].sum()
                    zone_adv    = zone_group["ADV"].sum()
                    zone_pps    = zone_pkg / (zone_ships if zone_ships != 0 else 1)

                    zone_wpps   = (zone_group["WeightPerPice"] * zone_group["_orig_pq"]).sum() / max(zone_group["_orig_pq"].sum(), 1e-9)

                    zone_fg     = zone_group["BaseGrossReportingAmount"].sum()
                    zone_fn     = zone_group["BaseNetReportingAmount"].sum()
                    zone_cb     = zone_group["CostBasis"].sum()
                    zone_fd     = ((zone_fg - zone_fn) * 100) / (zone_fg if zone_fg != 0 else 1)
                    zone_rpp    = zone_fn / (zone_pkg if zone_pkg != 0 else 1)
                    details.append({
                        "Movement": zone_group["MovementDirectionCode"].iloc[0],
                        "Mode": zone_group["Mode"].iloc[0],
                        "Lane": zone_group["Lane"].iloc[0],
                        "service": service_code,
                        "Zone": zone_val,
                        "ServiceGroup": service_group,
                        "Volume": int(round(zone_vol)),
                        "ADV": float(f"{zone_adv:.1f}"),
                        "PPS": float(f"{zone_pps:.2f}"),
                        "WeightPiece": float(f"{zone_wpps:.2f}"),
                        "FreightGross": f"$ {zone_fg:,.2f}",
                        "FreightDiscount": f"{zone_fd:.2f}%",
                        "FreightRPP": f"$ {zone_rpp:.2f}",
                        "FreightNet": f"$ {zone_fn:,.2f}",
                        "FreightProfit": f"$ {(zone_fn - zone_cb):,.2f}",
                        "FreightOR": f"{safe_div(zone_cb, zone_fn):.2f}",
                    })

                # Service-level totals
                total_volume = round(group["Volume"].sum())
                total_adv = float(f"{group['ADV'].sum():.1f}")
                total_pps = float(f"{group['PackageQuantity'].sum() / (group['TotalShipments'].sum() if group['TotalShipments'].sum() != 0 else 1):.2f}")

                total_weight = float(f"{(group['WeightPerPice'] * group['_orig_pq']).sum() / max(group['_orig_pq'].sum(), 1e-9):.2f}")

                total_freight_gross = f"{group['BaseGrossReportingAmount'].sum():,.2f}"
                total_freight_net = f"{group['BaseNetReportingAmount'].sum():,.2f}"
                total_freight_disc = f"{((group['BaseGrossReportingAmount'].sum() - group['BaseNetReportingAmount'].sum()) * 100) / (group['BaseGrossReportingAmount'].sum() if group['BaseGrossReportingAmount'].sum() != 0 else 1):.2f}"
                total_freight_rpp = f"{group['BaseNetReportingAmount'].sum() / (group['PackageQuantity'].sum() if group['PackageQuantity'].sum() != 0 else 1):,.2f}"
                total_profit = f"{group['BaseNetReportingAmount'].sum() - group['CostBasis'].sum():,.2f}"
                total_or = f"{group['CostBasis'].sum() / (group['BaseNetReportingAmount'].sum() if group['BaseNetReportingAmount'].sum() != 0 else 1):.2f}"

                response_data.append({
                    "Movement": group["MovementDirectionCode"].iloc[0],
                    "Mode": group["Mode"].iloc[0],
                    "service": service_code,
                    "ServiceZone": "-",
                    "Volume": total_volume,
                    "ADV": total_adv,
                    "PPS":total_pps,
                    "WeightPiece": total_weight,
                    "FreightGross": f"$ {total_freight_gross}",
                    "FreightDiscount": f"{total_freight_disc}%",
                    "FreightRPP": f"$ {total_freight_rpp}",
                    "FreightNet": f"$ {total_freight_net}",
                    "FreightProfit": f"$ {total_profit}",
                    "FreightOR": f"{total_or}",
                    "details": details
                })
            log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response([{"data": response_data}], status=status.HTTP_200_OK)
        except Exception as e:
            log_error(
                "Shipping Profile Summary Zone API GET Method failed",
                context="ShippingProfileSummaryZoneAPIView_V1.get - Exception encountered",
                exc=e
            )
            log_info("Shipping Profile Summary Zone API GET Method", context="Shipping Profile Summary Zone API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(
                {"error": f"Something went wrong: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileCostwise(APIView):
    allowed_methods = ["GET"]

    def get(self,request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Started")
            empId=request.claims['EmpID']
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Costwise API GET Method", context=f"User Authentication : {empId}")
            log_debug("Shipping Profile Costwise API GET Method", context=f"Query : {str(user_number.query)}")
            if not user_number:
                log_warning("Shipping Profile Costwise API GET Method", context=f"Not accessible. Emp Id:{empId}")
                log_error("Shipping Profile Costwise API GET Method", context=f"Not accessible. Emp Id:{empId}")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error":"Inaccessible"},status=status.HTTP_400_BAD_REQUEST)
            
            AnzPktId = request.GET.get('AnalyzerPacketSystemNumber')
            ScnSysNum = request.GET.get('ScenarioSystemNumber')
            costBasis = request.GET.get('CostBasis')
            # revBasis = request.GET.get('RevenueBasis')
            BidNo = request.GET.get('BidNumber')
            AccNo = request.GET.get('AccountNumber')
            ServCode = request.GET.get('ServiceCode')
            servicefeaturetypecode=request.GET.get('servicefeaturetypecode')
            if not AnzPktId:
                log_warning("Shipping Profile Costwise API GET Method", context="Analyzer Packet Id missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Analyzer Packet Id missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Analyzer Packet Id"}, status=status.HTTP_400_BAD_REQUEST)
            if not ScnSysNum:
                log_warning("Shipping Profile Costwise API GET Method", context="Scenario System Number missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Scenario System Number missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Scenario System Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not costBasis:
                log_warning("Shipping Profile Costwise API GET Method", context="Cost basis missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Cost basis missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Cost Basis"}, status=status.HTTP_400_BAD_REQUEST)
            # if not revBasis:
            #     logger.warning(f"Revenue basis missing")
            #     return Response({"error": "Missing Revenue Basis"}, status=status.HTTP_400_BAD_REQUEST)
            if not BidNo:
                log_warning("Shipping Profile Costwise API GET Method", context="Bid Number missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Bid Number missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Bid Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not AccNo:
                log_warning("Shipping Profile Costwise API GET Method", context="Account Number missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Account Number missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Account Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not ServCode:
                log_warning("Shipping Profile Costwise API GET Method", context="Service Code missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Service Code missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Service Code"}, status=status.HTTP_400_BAD_REQUEST)
            if not servicefeaturetypecode:
                log_warning("Shipping Profile Costwise API GET Method", context="Service Feature Type Code missing")
                log_error("Shipping Profile Costwise API GET Method", context=f"Service Feature Type Code missing")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Service Feature Type Code"}, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch scenario to get the actual ScenarioNumber for BigQuery
            # Handle both ScenarioSystemNumber (PK) and ScenarioNumber (BigQuery field) for flexibility
            try:
                scenario = TScenario.objects.get(ScenarioSystemNumber=ScnSysNum)
                scenario_number = scenario.ScenarioNumber
                scenario_name = scenario.ScenarioName
                if not scenario.SummaryGeneratedIndicator:
                    base_scenario_number = getScenarioHierarchy(scenario.ScenarioSystemNumber)
                    if base_scenario_number is not None:
                        scenario_number = base_scenario_number
                scenario_number = str(scenario_number)
                log_debug("Shipping Profile Costwise API GET Method", context=f"Found Scenario by ScenarioSystemNumber: {scenario_name} (ScenarioNumber: {scenario_number})")
            except TScenario.DoesNotExist:
                # Try to find by ScenarioNumber + AnalyzerPacketSystemNumber in case user passed ScenarioNumber
                try:
                    scenario = TScenario.objects.get(
                        AnalyzerPacketSystemNumber=AnzPktId,
                        ScenarioNumber=ScnSysNum
                    )
                    scenario_number = scenario.ScenarioNumber
                    scenario_name = scenario.ScenarioName
                    if not scenario.SummaryGeneratedIndicator:
                        base_scenario_number = getScenarioHierarchy(scenario.ScenarioSystemNumber)
                        if base_scenario_number is not None:
                            scenario_number = base_scenario_number
                    scenario_number = str(scenario_number)
                    log_debug("Shipping Profile Costwise API GET Method", context=f"Found Scenario by ScenarioNumber: {scenario_name} (ScenarioNumber: {scenario_number})")
                except TScenario.DoesNotExist:
                    log_warning(
                        "Shipping Profile Costwise API GET Method",
                        context=f"Scenario not found for AnalyzerPacket {AnzPktId} with ScenarioSystemNumber/ScenarioNumber: {ScnSysNum}"
                    )
                    log_error("Shipping Profile Costwise API GET Method", context=f"Scenario not found for AnalyzerPacket {AnzPktId} with value: {ScnSysNum}")
                    log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                    return Response({"error": f"Scenario not found for AnalyzerPacket {AnzPktId} and ScenarioSystemNumber/ScenarioNumber: {ScnSysNum}"}, status=status.HTTP_404_NOT_FOUND)
            
            REVENUE_FIELD_MAP = {
                                "Fuel Surcharge": {
                                    "cost": "FuelSurchargeBaseBidCost",
                                    "marginal": "FuelSurchargeMarginalCost"
                                },
                                "Transportation Charges": {
                                    "cost": "TransportationChargesBaseBidCost",
                                    "marginal": "TransportationChargesMarginalCost"
                                },
                                "Pickup And Delivery": {
                                    "cost": "PickupAndDeliveryBaseBidCost",
                                    "marginal": "PickupAndDeliveryMarginalCost"
                                },
                                "Returns": {
                                    "cost": "ReturnsBaseBidCost",
                                    "marginal": "ReturnsMarginalCost"
                                },
                                "Other Charges": {
                                    "cost": "OtherChargesBaseBidCost",
                                    "marginal": "OtherChargesMarginalCost"
                                },
                                "Custom Brokerage": {
                                    "cost": "CustomBrokerageBaseBidCost",
                                    "marginal": "CustomBrokerageMarginalCost"
                                }
                            }

            scenario_bid_details=TAnalyzerScenarioBid.objects\
            .filter(ScenarioSystemNumber=ScnSysNum)\
            .values('ScenarioSystemNumber',
                    'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber')
            log_debug("Shipping Profile Costwise API GET Method", context=f"Query : {str(scenario_bid_details.query)}")
            scenario_bid_details=pd.DataFrame(scenario_bid_details)
            
            # Handle empty scenario_bid_details
            if not scenario_bid_details.empty and 'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber' in scenario_bid_details.columns:
                scenario_bid_details.rename(columns={
                    'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber':'BidNumber'
                },inplace=True)
                bidNosList=scenario_bid_details['BidNumber'].unique()
            else:
                # No bid details found, initialize empty list
                bidNosList = []
            
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='BaseBid'
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='Marginal'
            else:
                raise Exception(f"Incorrect Cost Basis")
            
            acc_str,serv_str,servicefeaturetypecode_filter='','',''
            if AccNo.strip().lower() != 'all':
                AccNo = ast.literal_eval(AccNo)
                if not 'All' in AccNo:
                    AccNo=f"('{AccNo[0]}')" if len(AccNo)==1 else tuple(AccNo)
                    acc_str=f"AND BillToAccountNumber in {AccNo}"
            if ServCode.strip().lower() != 'all':
                ServCode = ast.literal_eval(ServCode)
                if not 'All' in ServCode:
                    ServCode=f"('{ServCode[0]}')" if len(ServCode)==1 else tuple(ServCode)
                    serv_str=f"AND ServiceCode in {ServCode}"
            if BidNo.strip().lower() != 'all':
                BidNo = ast.literal_eval(BidNo)
                bidNosList=BidNo
            else:
                # If BidNo is 'All' and bidNosList is empty, use all available bids from BigQuery
                if len(bidNosList) == 0:
                    # Query to get distinct bid numbers for this analyzer
                    temp_query = f"""
                    SELECT DISTINCT BidNumber 
                    FROM {shipping_profile_summary}
                    WHERE AnalyzerPacketID = '{AnzPktId}'
                    AND ScenarioNumber = '{scenario_number}'
                    LIMIT 100
                    """
                    try:
                        temp_result = client.query(temp_query).to_dataframe()
                        if not temp_result.empty:
                            bidNosList = temp_result['BidNumber'].tolist()
                        else:
                            log_warning("Shipping Profile Costwise API GET Method", context=f"No bid numbers found in BigQuery for Analyzer {AnzPktId}, ScenarioNumber {scenario_number}")
                            return Response({"error": "No bid numbers found for the given parameters"}, status=status.HTTP_404_NOT_FOUND)
                    except Exception as e:
                        log_error("Shipping Profile Costwise API GET Method", context=f"Error fetching bid numbers: {str(e)}")
                        return Response({"error": f"Error fetching bid numbers: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            
            
            if servicefeaturetypecode.strip().lower() != 'all':
                servicefeaturetypecode=ast.literal_eval(servicefeaturetypecode)
                if not 'All' in servicefeaturetypecode:
                    servicefeaturetypecode_list=f"('{servicefeaturetypecode[0]}')" if len(servicefeaturetypecode)==1 else tuple(servicefeaturetypecode)
                    servicefeaturetypecode_filter=f" AND ServiceFeatureTypeCode in {servicefeaturetypecode_list}"
            bidNosList=f"('{bidNosList[0]}')" if len(bidNosList)==1 else tuple(bidNosList)
            # if revBasis != 'All':
            #     revBasis = ast.literal_eval(revBasis)

            '''query=f"""
            SELECT
            MovementDirectionCode AS Movement,
            Mode,
            ServiceCode AS name,
            DeliveryZoneNumber AS Zone,
            SUM(ADV) AS ADV,
            SUM(PackageQuantity) AS Volume,
            SUM(BillableWeight*PackageQuantity) AS WeightPiece,
            SUM(AvgCube*PackageQuantity) AS AvgCube,
            SUM(CubeFactor*PackageQuantity) AS AvgCubeFactor,
            SUM(PUDens*PickupEquivalentStops) AS PUDens,
            SUM(Dllens*DeliveryEquivalentStops) AS DLDens,
            SUM(Pickup{costBasis}Cost*PackageQuantity) AS PU,
            SUM(LocalSort{costBasis}Cost*PackageQuantity) AS LS,
            SUM(CentralSort{costBasis}Cost*PackageQuantity) AS CS,
            SUM(AirRamp{costBasis}Cost*PackageQuantity) AS AR,
            SUM(Airfeed{costBasis}Cost*PackageQuantity) AS JF,
            SUM(Feeder{costBasis}Cost*PackageQuantity) AS GF,
            SUM(Brokerage{costBasis}Cost*PackageQuantity) AS BR,
            SUM(PreDelivery{costBasis}Cost*PackageQuantity) AS PD,
            SUM(Delivery{costBasis}Cost*PackageQuantity) AS DL,
            SUM(NonOperating{costBasis}Cost*PackageQuantity) AS `NO`,
            SUM(Other{costBasis}Cost*PackageQuantity) AS OTH,
            SUM(Total{costBasis}FrieghtCost) AS TotalFreightCost,
            SUM(PackageQuantity) AS PkgQty,
            SUM(TotalShipments) AS ShpQty,
            SUM(PickupEquivalentStops) AS PickupEqStop,
            SUM(DeliveryEquivalentStops) AS DeliveryEqStop
            FROM {shipping_profile_summary}
            WHERE AnalyzerPacketID = '{AnzPktId}'
            AND ScenarioNumber = '{scenario_number}'
            AND BidNumber in {bidNosList}
            {acc_str}
            {servicefeaturetypecode_filter}
            {serv_str}
            GROUP BY
            MovementDirectionCode,
            Mode,
            ServiceCode,
            DeliveryZoneNumber
            """'''
            query=f"""
            SELECT
            BillToAccountNumber,
            MovementDirectionCode AS Movement,
            Mode,
            ServiceCode AS name,
            COALESCE(NULLIF(TRIM(ServiceGroup), ""), CONCAT(ServiceCode," - ",ContainerCode)) AS ServiceGroup,
            DeliveryZoneNumber AS Zone,
            SUM(ADV) AS ADV,
            SUM(PackageQuantity) AS Volume,
            SUM(BillableWeight*PackageQuantity) AS WeightPiece,
            SUM(CubeFactor*PackageQuantity) AS AvgCube,
            SUM(AvgCube*PackageQuantity) AS AvgCubeFactor,
            SUM(PUDens*PickupEquivalentStops) AS PUDens,
            SUM(Dllens*DeliveryEquivalentStops) AS DLDens,
            SUM(Pickup{costBasis}Cost*PackageQuantity) AS PU,
            SUM(LocalSort{costBasis}Cost*PackageQuantity) AS LS,
            SUM(CentralSort{costBasis}Cost*PackageQuantity) AS CS,
            SUM(AirRamp{costBasis}Cost*PackageQuantity) AS AR,
            SUM(Airfeed{costBasis}Cost*PackageQuantity) AS JF,
            SUM(Feeder{costBasis}Cost*PackageQuantity) AS GF,
            SUM(Brokerage{costBasis}Cost*PackageQuantity) AS BR,
            SUM(PreDelivery{costBasis}Cost*PackageQuantity) AS PD,
            SUM(Delivery{costBasis}Cost*PackageQuantity) AS DL,
            SUM(NonOperating{costBasis}Cost*PackageQuantity) AS `NO`,
            SUM(Other{costBasis}Cost*PackageQuantity) AS OTH,
            SUM(Total{costBasis}FrieghtCost) AS TotalFreightCost,
            SUM(PackageQuantity) AS PkgQty,
            SUM(TotalShipments) AS ShpQty,
            SUM(PickupEquivalentStops) AS PickupEqStop,
            SUM(DeliveryEquivalentStops) AS DeliveryEqStop
            FROM {shipping_profile_summary}
            WHERE AnalyzerPacketID = '{AnzPktId}'
            AND ScenarioNumber = '{scenario_number}'
            AND BidNumber in {bidNosList}
            {acc_str}
            {servicefeaturetypecode_filter}
            {serv_str}
            GROUP BY
            BillToAccountNumber,
            MovementDirectionCode,
            Mode,
            ServiceCode,
            ServiceGroup,
            DeliveryZoneNumber
            """
            log_debug("Shipping Profile Costwise API GET Method", context=f"BigQuery : {query}")
            df=client.query(query=query).to_dataframe()
            if df.empty:
                log_info("Shipping Profile Costwise API GET Method", context=f"No data found for the provided filters from BigQuery")
                log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data for provided inputs"}, status=status.HTTP_200_OK)
            
            numeric_cols = ['ADV','Volume','WeightPiece','AvgCube','AvgCubeFactor','PUDens','DLDens',
                            'PU','LS','CS','AR','JF','GF','BR','PD','DL','NO','OTH',
                            'TotalFreightCost','PkgQty','ShpQty','PickupEqStop','DeliveryEqStop']
            for c in numeric_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(float)

            # Apply per-row AF BEFORE re-aggregating to handle mixed HPLD/OPLD data correctly.
            # The BQ AnnualizationFactor column stores HPLD factor and is wrong for OPLD rows;
            # use Django get_annualization_factor per BillToAccountNumber instead.
            _af_cols = ['Volume', 'WeightPiece', 'AvgCube', 'AvgCubeFactor',
                        'PU', 'LS', 'CS', 'AR', 'JF', 'GF', 'BR', 'PD', 'DL', 'NO', 'OTH',
                        'PkgQty']
            df["_af"] = df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(AnzPktId, account_number=str(acct))
            )
            for col in _af_cols:
                if col in df.columns:
                    df[col] = df[col] * df["_af"]
            # Re-aggregate to original dimensions (drop BillToAccountNumber)
            _c_grp = ["Movement", "Mode", "name", "Zone"]
            _c_sums = ['ADV', 'Volume', 'WeightPiece', 'AvgCube', 'AvgCubeFactor',
                       'PUDens', 'DLDens', 'PU', 'LS', 'CS', 'AR', 'JF', 'GF', 'BR',
                       'PD', 'DL', 'NO', 'OTH', 'TotalFreightCost',
                       'PkgQty', 'ShpQty', 'PickupEqStop', 'DeliveryEqStop']
            df = df.groupby(_c_grp, as_index=False)[_c_sums].sum()


            grpdf = df.groupby(['Movement','Mode','name']).agg({
                'ADV':'sum',
                'Volume':'sum',
                'WeightPiece':'sum',
                'AvgCube':'sum',
                'AvgCubeFactor':'sum',
                'PUDens':'sum',
                'DLDens':'sum',
                'PU':'sum',
                'LS':'sum',
                'CS':'sum',
                'AR':'sum',
                'JF':'sum',
                'GF':'sum',
                'BR':'sum',
                'PD':'sum',
                'DL':'sum',
                'NO':'sum',
                'OTH':'sum',
                'TotalFreightCost':'sum',
                'PickupEqStop':'sum',
                'DeliveryEqStop':'sum',
                'PkgQty':'sum',
                'ShpQty':'sum'
            }).reset_index()
            
            div_cols = ['WeightPiece','AvgCube','AvgCubeFactor',
                             'PU','LS','CS','AR','JF','GF','BR','PD','DL','NO','OTH','TotalFreightCost']
            roundoff_cols = ['WeightPiece','AvgCube','AvgCubeFactor','ADV']
            
            df[div_cols] = df[div_cols].div(df["PkgQty"].replace(0, 1), axis=0).round(2)
            df[roundoff_cols]=df[roundoff_cols].round(2).astype(str)
            df['Volume'] = df['Volume'].round(0).astype(int).astype(str)
            df['PPS']=df['PkgQty'].div(df['ShpQty'].replace(0, 1), axis=0).round(2).astype(str)
            df['PUDens']=df['PUDens'].div(df['PickupEqStop'].replace(0, 1), axis=0).round(2).astype(str)
            df['DLDens']=df['DLDens'].div(df['DeliveryEqStop'].replace(0, 1), axis=0).round(2).astype(str)
            df['Lane']='-'
            df['Costadj']='-'
            df['Newcost']=df['TotalFreightCost']

            grpdf[div_cols] = grpdf[div_cols].div(grpdf["PkgQty"].replace(0, 1), axis=0).round(2)
            grpdf[roundoff_cols]=grpdf[roundoff_cols].round(2).astype(str)
            grpdf['Volume'] = grpdf['Volume'].round(0).astype(int).astype(str)
            grpdf['PPS']=grpdf['PkgQty'].div(grpdf['ShpQty'].replace(0, 1), axis=0).round(2).astype(str)
            grpdf['PUDens']=grpdf['PUDens'].div(grpdf['PickupEqStop'].replace(0, 1), axis=0).round(2).astype(str)
            grpdf['DLDens']=grpdf['DLDens'].div(grpdf['DeliveryEqStop'].replace(0, 1), axis=0).round(2).astype(str)
            grpdf['Lane']='-'
            grpdf['Zone']='-'
            grpdf['Costadj']='-'
            grpdf['Newcost']=grpdf['TotalFreightCost']

            cost_cols = ['PU','LS','CS','AR','JF','GF','BR','PD','DL','NO','OTH','TotalFreightCost','Newcost']
            df[cost_cols] = df[cost_cols].applymap(lambda x: f"$ {x:,}")
            grpdf[cost_cols] = grpdf[cost_cols].applymap(lambda x: f"$ {x:,}")

            lst=['Movement','Mode','name','Zone','Lane','Volume','ADV','PPS',
                 'WeightPiece','AvgCube','AvgCubeFactor','PUDens','DLDens','PU','LS','CS','AR',
                 'JF','GF','BR','PD','DL','NO','OTH','TotalFreightCost','Costadj','Newcost']
            df=df[lst]
            grpdf=grpdf[lst]

            data_list=[]
            for _,row in grpdf.iterrows():
                data_each=row.to_dict()
                tempdf=df[(df['Movement']==row['Movement'])\
                        &(df['Mode']==row['Mode'])&(df['name']==row['name'])]
                tempdf.sort_values(by='Zone',inplace=True,na_position='last')
                details=tempdf.to_dict(orient='records')
                data_each['details']=details
                data_list.append(data_each)
            final=[{'Scenario':scenario_name,'data':data_list}]
            log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(final, status=status.HTTP_200_OK)

        except Exception as e:
            log_error(
                "Shipping Profile Costwise API GET Method failed",
                context="ShippingProfileCostwiseAPIView.get - Exception encountered",
                exc=e
            )
            log_info("Shipping Profile Costwise API GET Method", context="Shipping Profile Costwise API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileSummaryServiceAPIView(APIView):
    allowed_methods = ["GET"]
    def get(self, request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Started")
            empId=request.claims['EmpID']
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Summary Service API GET Method", context=f"User Authentication : {empId}")
            log_info("Shipping Profile Summary Service API GET Method", context=f"User Number : {user_number.query}")
            if not user_number:
                log_error("Shipping Profile Summary Service API GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)
        
            analyzer_id = request.query_params.get("analyzer_id")
            scenario_system_number = request.query_params.get("scenario_system_number")
            scenario_number = request.query_params.get("scenario_number")
            bid_number = request.query_params.get("bid_number", "all")
            acc_nums = request.query_params.get("accounts", "all")
            svc_codes = request.query_params.get("service", "all")
            costBasis = request.query_params.get("costBasis")
            servicefeaturetypecode=request.query_params.get("servicefeaturetypecode","all")
            if not servicefeaturetypecode:
                log_error("Shipping Profile Summary Service API GET Method", context=f"Service Feature Type Code missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing servicefeaturetypecode"}, status=status.HTTP_400_BAD_REQUEST)
            if not analyzer_id:
                log_warning("Shipping Profile Summary Service API GET Method", context="Analyzer Packet Id missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Analyzer Packet Id missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Analyzer Packet Id"}, status=status.HTTP_400_BAD_REQUEST)
            if not scenario_system_number:
                log_warning("Shipping Profile Summary Service API GET Method", context="Scenario System Number missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Scenario System Number missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Scenario System Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not scenario_number:
                log_warning("Shipping Profile Summary Service API GET Method", context="Scenario Number missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Scenario Number missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Scenario Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not bid_number:
                log_warning("Shipping Profile Summary Service API GET Method", context="Bid Number missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Bid Number missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Bid Number"}, status=status.HTTP_400_BAD_REQUEST)
            if not acc_nums:
                log_warning("Shipping Profile Summary Service API GET Method", context="Account Numbers missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Account Numbers missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Account Numbers"}, status=status.HTTP_400_BAD_REQUEST)
            if not svc_codes:
                log_warning("Shipping Profile Summary Service API GET Method", context="Service Codes missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Service Codes missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing Service Codes"}, status=status.HTTP_400_BAD_REQUEST)
            if not costBasis:
                log_warning("Shipping Profile Summary Service API GET Method", context="Cost basis missing")
                log_error("Shipping Profile Summary Service API GET Method", context=f"Cost basis missing")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing costBasis"}, status=status.HTTP_400_BAD_REQUEST)
            
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber=scenario_system_number
            ).values(
                "ScenarioSystemNumber",
                "ScenarioSystemNumber__ScenarioNumber",
                "ScenarioSystemNumber__SummaryGeneratedIndicator",
                "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber",
            )
            log_debug("Shipping Profile Summary Service API GET Method", context=f"Query : {str(bid_info.query)}")
            if not bid_info:
                log_error("Shipping Profile Summary Service API GET Method", context=f"No bids found for Scenario System Number: {scenario_system_number}")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No bids found"}, status=status.HTTP_400_BAD_REQUEST)

            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(
                columns={
                    "ScenarioSystemNumber__ScenarioNumber": "ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator": "SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber": "BidNumber",
                },
                inplace=True,
            )
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            if bid_number.lower() == "all":
                bid_list = bid_df["BidNumber"].dropna().unique().tolist()
            else:
                bid_list = bid_number.split(",")

            # --- Step 3: Adjust ScenarioNumber based on SummaryGeneratedIndicator ---
            bid_df["ScenarioNumber"] = bid_df.apply(
                lambda r: getScenarioHierarchy(r["ScenarioSystemNumber"]) if not r["SummaryGeneratedIndicator"] else str(r["ScenarioNumber"]),
                axis=1)
            
            servicefeaturetypecode=servicefeaturetypecode.strip("'\"")
            scenario_number=bid_df['ScenarioNumber'].unique()[0]
            account_filter = ""
            service_filter = ""
            servicefeaturetypecode_filter=""
            bid_param = "(" + ",".join([f"'{b}'" for b in bid_list]) + ")"
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            acc_nums = acc_nums.split(",") if acc_nums.lower() != "all" else ["All"]
            service_codes = svc_codes.split(",") if svc_codes.lower() != "all" else ["All"]
            servicefeaturetypecode_list=servicefeaturetypecode.split(",") if servicefeaturetypecode.lower()!="all" else ["All"]
            account_filter = " AND BillToAccountNumber IN (" + ",".join(f'"{x}"' for x in acc_nums) + ")" if "All" not in acc_nums else ""
            service_filter = " AND ServiceCode IN (" + ",".join(f'"{x}"' for x in service_codes) + ")" if "All" not in service_codes else ""
            servicefeaturetypecode_filter = " AND ServiceFeatureTypeCode IN (" + ",".join(f'"{x}"' for x in servicefeaturetypecode_list) + ")" if "All" not in servicefeaturetypecode_list else ""
            # --- 2. Validate Cost Basis ---
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='TotalBaseBidFrieghtCost'
                selected_fields = [v["cost"] for v in REVENUE_FIELD_MAP.values()]
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='TotalMarginalFrieghtCost'
                selected_fields=[v["marginal"] for v in REVENUE_FIELD_MAP.values()]
            else:
                raise Exception(f"Incorrect Cost Basis")
            costBasis_field=f"sum({costBasis}) as FreightCost"
            total_cost_expr = costBasis + " + " + " + ".join(selected_fields)

            # --- 3. Build BigQuery query ---
            project_id =  os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table = os.getenv("TABLE_SUMMARY_SHIPPING_PROFILE")
            # ------
            
            query=f"""
                SELECT 

                BillToAccountNumber,

                MovementDirectionCode AS Movement,
                Mode,
                ServiceCode AS Service,
                COALESCE(NULLIF(TRIM(ServiceGroup), ""), CONCAT(ServiceCode," - ",ContainerCode)) AS ServiceGroup,
                SUM(ADV) AS ADV,
                SUM(BillableWeight*PackageQuantity) AS Weight,
                SUM(CAST(DeliveryZoneNumber AS INT)*PackageQuantity) AS Zone,
                SUM(BaseGrossReportingAmount
                +FuelSurchargeGrossUSD+TransportationChargesGrossUSD+PickupAndDeliveryGrossUSD
                +ReturnsGrossUSD+OtherChargesGrossUSD+CustomBrokerageGrossUSD) AS TotalGrossRevenue,
                SUM(BaseNetReportingAmount
                +FuelSurchargeNetUSD+TransportationChargesNetUSD+PickupAndDeliveryNetUSD
                +ReturnsNetUSD+OtherChargesNetUSD+CustomBrokerageNetUSD) AS TotalNetRevenue,
                sum({total_cost_expr}) AS TotalCost,
                SUM(TotalShipments) AS ShpQty,
                SUM(PackageQuantity) AS totalvolume,
                SUM(BaseGrossReportingAmount) AS BaseGrossReportingAmount,
                SUM(BaseNetReportingAmount) AS BaseNetReportingAmount,
                SUM({costBasis}) AS TotalFreightCost
                FROM `{project_id}.{dataset}.{table}`
                WHERE AnalyzerPacketID='{analyzer_id}' and ScenarioNumber='{scenario_number}'
                AND BidNumber in {bid_param}
                {account_filter}
                {service_filter}
                {servicefeaturetypecode_filter}

                GROUP BY BillToAccountNumber, MovementDirectionCode, Mode, ServiceCode, ServiceGroup

            """
            log_info(f"Shipping Profile Summary Service API GET Method", context=f"BigQuery : {query}")
            
            log_info(
                "Executing BigQuery for analyzer",
                context="Shipping Profile Summary Service API GET Method - BigQuery execution",
                analyzer_id=analyzer_id
            )
            result = client.query(query).result()
            result_data = [dict(row) for row in result]
            if not result_data:
                log_info("Shipping Profile Summary Service API GET Method", context=f"No data found for the provided filters from BigQuery")
                log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response(
                    {"message": "No data for provided inputs"},
                    status=status.HTTP_200_OK,
                )
            log_info(
                "Fetched data for the corresponding filters",
                context="Shipping Profile Summary Service API GET Method - BigQuery results ready"
            )
            df = pd.DataFrame(result_data)
            _numeric_cols = ['totalvolume', 'ShpQty', 'ADV', 'Zone', 'Weight',
                             'BaseGrossReportingAmount', 'BaseNetReportingAmount',
                             'TotalGrossRevenue', 'TotalNetRevenue',
                             'TotalFreightCost', 'TotalCost']
            df[_numeric_cols] = df[_numeric_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
            movement_map = dict(
                                TServiceHierarchy.objects
                                .values_list("MovementDirectionIdentificationNumber", "MovementDirectionName")
                            )
            service_map = dict(
                                TServiceHierarchy.objects
                                .values_list("PricingCoreServiceCode", "PricingCoreServiceCodeDescriptionText")
                            )
            df["Movement"] = df["Movement"].map(movement_map).fillna(df["Movement"])
            df["Service"] = df["Service"].map(service_map).fillna(df["Service"])
            # Keep ServiceGroup exactly as provided by summary table (with SQL fallback)
            # so it preserves service + container + res/com + flow-through semantics.
            df["ServiceGroup"] = df["ServiceGroup"].fillna("Unknown").astype(str)

            # Apply per-row AF BEFORE re-aggregating to correctly handle mixed HPLD/OPLD data.
            df["_af"] = df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(analyzer_id, account_number=str(acct))
            )
            df["totalvolume"] = df["totalvolume"] * df["_af"]
            # Weight = SUM(BW*PQ): scale by AF so avg weight = SUM(BW*PQ) / SUM(PQ) after division.
            df["Weight"] = df["Weight"] * df["_af"]
            # Re-aggregate to original dimensions (drop BillToAccountNumber)
            _s_sums = ['ADV', 'Weight', 'Zone', 'TotalGrossRevenue', 'TotalNetRevenue',
                       'TotalCost', 'ShpQty', 'totalvolume', 'BaseGrossReportingAmount',
                       'BaseNetReportingAmount', 'TotalFreightCost']
            df = df.groupby(['Movement', 'Mode', 'Service', 'ServiceGroup'], as_index=False)[_s_sums].sum()


            grp_df=df.groupby(['Movement','Mode','Service'],as_index=False).agg({
                'ADV':'sum',
                'Weight':'sum',
                'Zone':'sum',
                'BaseGrossReportingAmount':'sum',
                'BaseNetReportingAmount':'sum',
                'totalvolume':'sum',
                'ShpQty':'sum',
                'TotalGrossRevenue':'sum',
                'TotalNetRevenue':'sum',
                'TotalCost':'sum',
                'TotalFreightCost':'sum'
            })

            # Individual Caluclations
            div_cols=['Zone','Weight']
            df[div_cols] = df[div_cols].div(df["totalvolume"].replace(0, 1), axis=0).round(2)
            df['PPS']=df['totalvolume'].div(df['ShpQty'].replace(0, 1), axis=0).round(2)
            df['basedisc']=((df['BaseGrossReportingAmount']-df['BaseNetReportingAmount'])*100).div(df['BaseGrossReportingAmount'].replace(0, 1), axis=0).round(2)
            df['baserpp']=df['BaseNetReportingAmount'].div(df['totalvolume'].replace(0, 1), axis=0).round(2)
            df['baseprofit']=(df['BaseNetReportingAmount']-df['TotalFreightCost']).round(2)
            df['baseor']=df['TotalFreightCost'].div(df['BaseNetReportingAmount'].replace(0, 1), axis=0).round(2)
            df['totaldisc']=((df['TotalGrossRevenue'] - df['TotalNetRevenue'])*100).div(df['TotalGrossRevenue'].replace(0, 1), axis=0).round(2)
            df['totalrpp']=df['TotalNetRevenue'].div(df['totalvolume'].replace(0, 1), axis=0).round(2)
            df['totalprofit']=(df['TotalNetRevenue'] - df['TotalCost']).round(2)
            df['totalor']=df['TotalCost'].div(df['TotalNetRevenue'].replace(0, 1), axis=0).round(2)
            round_list=['ADV','BaseGrossReportingAmount','BaseNetReportingAmount','TotalGrossRevenue',
                        'TotalNetRevenue','TotalCost','TotalFreightCost']
            df[round_list]=df[round_list].round(2)
            df["totalvolume"]=df["totalvolume"].round(0).astype(int)

            # Grouped Caluclations
            div_cols=['Zone','Weight']
            grp_df[div_cols] = grp_df[div_cols].div(grp_df["totalvolume"].replace(0, 1), axis=0).round(2)
            grp_df['PPS']=grp_df['totalvolume'].div(grp_df['ShpQty'].replace(0, 1), axis=0).round(2)
            grp_df['basedisc']=((grp_df['BaseGrossReportingAmount']-grp_df['BaseNetReportingAmount'])*100).div(grp_df['BaseGrossReportingAmount'].replace(0, 1), axis=0).round(2)
            grp_df['baserpp']=grp_df['BaseNetReportingAmount'].div(grp_df['totalvolume'].replace(0, 1), axis=0).round(2)
            grp_df['baseprofit']=(grp_df['BaseNetReportingAmount']-grp_df['TotalFreightCost']).round(2)
            grp_df['baseor']=grp_df['TotalFreightCost'].div(grp_df['BaseNetReportingAmount'].replace(0, 1), axis=0).round(2)
            grp_df['totaldisc']=((grp_df['TotalGrossRevenue'] - grp_df['TotalNetRevenue'])*100).div(grp_df['TotalGrossRevenue'].replace(0, 1), axis=0).round(2)
            grp_df['totalrpp']=grp_df['TotalNetRevenue'].div(grp_df['totalvolume'].replace(0, 1), axis=0).round(2)
            grp_df['totalprofit']=(grp_df['TotalNetRevenue'] - grp_df['TotalCost']).round(2)
            grp_df['totalor']=grp_df['TotalCost'].div(grp_df['TotalNetRevenue'].replace(0, 1), axis=0).round(2)
            grp_df[round_list]=grp_df[round_list].round(2)
            grp_df["totalvolume"]=grp_df["totalvolume"].round(0).astype(int)
            dollar_cols=['TotalGrossRevenue','TotalNetRevenue','totalrpp','baserpp','baseprofit','totalprofit','BaseGrossReportingAmount','BaseNetReportingAmount']
            for dc in dollar_cols:
                df[dc]=df[dc].apply(lambda x: f"$ {float(x):,.2f}")
                grp_df[dc]=grp_df[dc].apply(lambda x: f"$ {float(x):,.2f}")

            df[df.columns]=df[df.columns].astype(str)
            grp_df[grp_df.columns]=grp_df[grp_df.columns].astype(str)
            percent_cols=['basedisc','totaldisc']
            for pc in percent_cols:
                df[pc]=df[pc]+'%'
                grp_df[pc]=grp_df[pc]+'%'
            
            
            join_cols=['Movement','Mode','Service','Zone','Weight','PPS','basedisc','baserpp','baseprofit','baseor',
                  'totaldisc','totalrpp','totalprofit','totalor','ADV','totalvolume','BaseGrossReportingAmount','BaseNetReportingAmount','TotalGrossRevenue','TotalNetRevenue']
            
            cols=['ServiceGroup','Zone','Weight','PPS','basedisc','baserpp','baseprofit','baseor',
                  'totaldisc','totalrpp','totalprofit','totalor','ADV','totalvolume','BaseGrossReportingAmount','BaseNetReportingAmount','TotalGrossRevenue','TotalNetRevenue']
            
            details = df.groupby(['Movement','Mode','Service']).apply(
                    lambda x: x[cols].to_dict('records')
                ).reset_index(name='details')
            
            grp_df=grp_df[join_cols].merge(details,on=['Movement','Mode','Service'],how='left')

            data_list=grp_df.to_dict(orient='records')
            final=[{'Scenario':scenario_number,'data':data_list}]
            log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(
                        final,
                        status=status.HTTP_200_OK,
                    )
        except Exception as e:
                    import traceback
                    print(traceback.print_exc())
                    log_error(
                        "Shipping Profile Summary Service API GET Method failed",
                        context="ShippingProfileSummaryServiceAPIView.get - Exception encountered",
                        exc=e
                    )
                    log_info("Shipping Profile Summary Service API GET Method", context="Shipping Profile Summary Service API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                    log_error("Shipping Profile Summary Service API GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
                    return Response(
                        {"error": f"Something went wrong: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )



@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileSummaryAccountAPIView(APIView):
    allowed_methods = ["GET"]
    def get(self, request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Started")
            empId=request.claims['EmpID']
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Summary Account API GET Method", context=f"User Authentication : {empId}")
            log_debug("Shipping Profile Summary Account API GET Method", context=f"Query : {user_number.query}")
            if not user_number:
                log_error("Shipping Profile Summary Account API GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)
        
            analyzer_id = request.query_params.get("analyzer_id")
            scenario_system_number = request.query_params.get("scenario_system_number")
            scenario_number = request.query_params.get("scenario_number")
            bid_number = request.query_params.get("bid_number", "all")
            acc_nums = request.query_params.get("accounts", "all")
            svc_codes = request.query_params.get("service", "all")
            servicefeaturetypecode=request.query_params.get("servicefeaturetypecode","all")
            costBasis = request.query_params.get("costBasis")
            if not servicefeaturetypecode:
                log_error("Shipping Profile Summary Account API GET Method", context=f"Service Feature Type Code missing")
                log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing servicefeaturetypecode"}, status=status.HTTP_400_BAD_REQUEST)
            if not costBasis:
                log_warning("Shipping Profile Summary Account API GET Method", context="Cost basis missing")
                log_error("Shipping Profile Summary Account API GET Method", context=f"Cost basis missing")
                log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing costBasis"}, status=status.HTTP_400_BAD_REQUEST)
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber=scenario_system_number
            ).values(
                "ScenarioSystemNumber",
                "ScenarioSystemNumber__ScenarioNumber",
                "ScenarioSystemNumber__SummaryGeneratedIndicator",
                "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber",
            )
            log_debug("Shipping Profile Summary Account API GET Method", context=f"Query : {str(bid_info.query)}")
            if not bid_info:
                log_error("Shipping Profile Summary Account API GET Method", context=f"No bids found for Scenario System Number: {scenario_system_number}")
                log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No bids found"}, status=status.HTTP_400_BAD_REQUEST)

            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(
                columns={
                    "ScenarioSystemNumber__ScenarioNumber": "ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator": "SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber": "BidNumber",
                },
                inplace=True,
            )
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            if bid_number.lower() == "all":
                bid_list = bid_df["BidNumber"].dropna().unique().tolist()
            else:
                bid_list = bid_number.split(",")

            # --- Step 3: Adjust ScenarioNumber based on SummaryGeneratedIndicator ---
            bid_df["ScenarioNumber"] = bid_df.apply(
                lambda r: getScenarioHierarchy(r['ScenarioSystemNumber']) if not r["SummaryGeneratedIndicator"] else str(r["ScenarioNumber"]),
                axis=1,
            )
            
            scenario_number=bid_df['ScenarioNumber'].unique()[0]
            account_filter = ""
            service_filter = ""
            servicefeaturetypecode_filter=""
            servicefeaturetypecode=servicefeaturetypecode.strip("'\"")  
            bid_param ="(" +",".join([f"'{b}'" for b in bid_list])+")"
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            acc_nums = acc_nums.split(",") if acc_nums.lower() != "all" else ["All"]
            service_codes = svc_codes.split(",") if svc_codes.lower() != "all" else ["All"]
            servicefeaturetypecode_list=servicefeaturetypecode.split(",") if servicefeaturetypecode.lower()!="all" else ["All"]
            account_filter = " AND BillToAccountNumber IN (" + ",".join(f'"{x}"' for x in acc_nums) + ")" if "All" not in acc_nums else ""
            service_filter = " AND ServiceCode IN (" + ",".join(f'"{x}"' for x in service_codes) + ")" if "All" not in service_codes else ""
            servicefeaturetypecode_filter = " AND ServiceFeatureTypeCode IN (" + ",".join(f'"{x}"' for x in servicefeaturetypecode_list) + ")" if "All" not in servicefeaturetypecode_list else ""
            # --- 2. Validate Cost Basis ---
            if costBasis.strip("'\"") == 'Fully Allocated Cost':
                costBasis='TotalBaseBidFrieghtCost'
                selected_fields = [v["cost"] for v in REVENUE_FIELD_MAP.values()]
            elif costBasis.strip("'\"") == 'Long Run Marginal Cost':
                costBasis='TotalMarginalFrieghtCost'
                selected_fields=[v["marginal"] for v in REVENUE_FIELD_MAP.values()]
            else:
                raise Exception(f"Incorrect Cost Basis")
            costBasis_field=f"sum({costBasis}) as FreightCost"
            total_cost_expr = costBasis + " + " + " + ".join(selected_fields)
            # --- 3. Build BigQuery query ---
            project_id = os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table = os.getenv("TABLE_SUMMARY_SHIPPING_PROFILE")
            query3=f"""
            SELECT 
                BillToAccountNumber,
                SUM(TotalShipments) AS Shipments,
                SUM(PackageQuantity) AS TotalVolume,
                SUM(ADV) AS ADV,
                SUM(CAST(DeliveryZoneNumber AS INT)*PackageQuantity) AS Zone,
                SUM(BillableWeight*PackageQuantity) AS Weight,
                SUM(BaseGrossReportingAmount) AS BaseGross,
                SUM(BaseNetReportingAmount) AS BaseNet,
                SUM(BaseGrossReportingAmount
                +FuelSurchargeGrossUSD+TransportationChargesGrossUSD+PickupAndDeliveryGrossUSD
                +ReturnsGrossUSD+OtherChargesGrossUSD+CustomBrokerageGrossUSD) AS GrossRevenue,
                SUM(BaseNetReportingAmount
                +FuelSurchargeNetUSD+TransportationChargesNetUSD+PickupAndDeliveryNetUSD
                +ReturnsNetUSD+OtherChargesNetUSD+CustomBrokerageNetUSD) AS NetRevenue,
                {costBasis_field},
                SUM({total_cost_expr}) AS TotalCost,
                FROM `{project_id}.{dataset}.{table}`
                WHERE AnalyzerPacketID='{analyzer_id}' and ScenarioNumber='{scenario_number}'
                AND BidNumber in {bid_param}
                {account_filter}
                {servicefeaturetypecode_filter}
                {service_filter}
                GROUP BY BillToAccountNumber"""
            log_info(
                "Executing BigQuery for analyzer",
                context="Shipping Profile Summary Account API GET Method - BigQuery execution",
                analyzer_id=analyzer_id
            )
            log_debug("Shipping Profile Summary Account API GET Method", context=f"BigQuery : {query3}")
            result = client.query(query3).result()
            result_data = [dict(row) for row in result]
            if not result_data:
                log_info("Shipping Profile Summary Account API GET Method", context=f"No data found for the provided filters from BigQuery")
                log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response(
                    {"message": "No data for provided inputs"},
                    status=status.HTTP_200_OK,
                )
            log_info(
                "Fetched data for the corresponding filters",
                context="Shipping Profile Summary Account API GET Method - BigQuery results ready"
            )
            df = pd.DataFrame(result_data)
            _numeric_cols = ['TotalVolume', 'Shipments', 'ADV', 'Zone', 'Weight',
                             'BaseGross', 'BaseNet', 'GrossRevenue', 'NetRevenue',
                             'FreightCost', 'TotalCost']
            df[_numeric_cols] = df[_numeric_cols].apply(pd.to_numeric, errors='coerce').fillna(0)
            PROJECT_ID=os.getenv("PROJECT_ID")
            CIDH_DATASET_ID=os.getenv("CIDH_DATASET_ID")
            CIDH_BIGQUERY_VIEW=os.getenv("CIDH_BIGQUERY_VIEW")
            bill_to_list = df["BillToAccountNumber"].unique().tolist()
            query2 = f"""
                    SELECT AccountNumber, AccountName, ParentMdmIdNumber, EstatCustomerNumber
                    FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                    WHERE AccountHierarchyLevelCode='AD'
                    AND AccountNumber IN ({','.join([f"'{x}'" for x in bill_to_list])})
                    """
            log_debug("Shipping Profile Summary Account API GET Method", context=f"BigQuery : {query2}")
            df2 = client.query(query2).to_dataframe()
            
            # Optimized: Fetch all hierarchy data in ONE query instead of N queries
            parent_mdm_ids = df2["ParentMdmIdNumber"].dropna().unique().tolist()
            
            parent_data = {}
            subparent_data = {}
            accountname_data = {}
            
            if parent_mdm_ids:
                # Fetch all parent and grandparent hierarchy levels in a single query
                query_hierarchy = f"""
                SELECT 
                    EstatCustomerNumber,
                    AccountName,
                    ParentMdmIdNumber,
                    AccountHierarchyLevelCode
                FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                WHERE EstatCustomerNumber IN ({','.join([f"'{x}'" for x in parent_mdm_ids])})
                AND AccountHierarchyLevelCode IN ('AB', 'AC')
                """
                log_debug("Shipping Profile Summary Account API GET Method", context=f"BigQuery Hierarchy: {query_hierarchy}")
                df_hierarchy = client.query(query_hierarchy).to_dataframe()
                
                # Build lookup dictionaries for fast access
                hierarchy_lookup = {}
                for _, row in df_hierarchy.iterrows():
                    hierarchy_lookup[row["EstatCustomerNumber"]] = {
                        "name": row["AccountName"],
                        "level": row["AccountHierarchyLevelCode"],
                        "parent_id": row["ParentMdmIdNumber"]
                    }
                
                # Get all grandparent IDs (for AC level accounts)
                grandparent_ids = [
                    v["parent_id"] for v in hierarchy_lookup.values() 
                    if v["level"] == "AC" and v["parent_id"] is not None
                ]
                
                grandparent_lookup = {}
                if grandparent_ids:
                    query_grandparents = f"""
                    SELECT 
                        EstatCustomerNumber,
                        AccountName
                    FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                    WHERE EstatCustomerNumber IN ({','.join([f"'{x}'" for x in grandparent_ids])})
                    AND AccountHierarchyLevelCode = 'AB'
                    """
                    log_debug("Shipping Profile Summary Account API GET Method", context=f"BigQuery Grandparents: {query_grandparents}")
                    df_grandparents = client.query(query_grandparents).to_dataframe()
                    grandparent_lookup = dict(zip(df_grandparents["EstatCustomerNumber"], df_grandparents["AccountName"]))
                
                # Now resolve hierarchy using in-memory lookups
                for _, row in df2.iterrows():
                    acct = row["AccountNumber"]
                    parent_id = row["ParentMdmIdNumber"]
                    accountname = row['AccountName']
                    accountname_data[acct] = accountname
                    
                    if parent_id is None or parent_id not in hierarchy_lookup:
                        parent_data[acct] = "No Parent"
                        subparent_data[acct] = "No Sub Parent"
                        continue
                    
                    hierarchy_info = hierarchy_lookup[parent_id]
                    level = hierarchy_info["level"]
                    name = hierarchy_info["name"]
                    
                    if level == "AB":
                        parent_data[acct] = name
                        subparent_data[acct] = "No Sub Parent"
                    elif level == "AC":
                        subparent_data[acct] = name
                        grandparent_id = hierarchy_info["parent_id"]
                        if grandparent_id and grandparent_id in grandparent_lookup:
                            parent_data[acct] = grandparent_lookup[grandparent_id]
                        else:
                            parent_data[acct] = "No Parent"
                    else:
                        parent_data[acct] = "No Parent"
                        subparent_data[acct] = "No Sub Parent"
            else:
                # No parent IDs to resolve
                for _, row in df2.iterrows():
                    acct = row["AccountNumber"]
                    accountname_data[acct] = row['AccountName']
                    parent_data[acct] = "No Parent"
                    subparent_data[acct] = "No Sub Parent"
            tm_values = [b for b in bill_to_list if b.startswith("TM")]
            if tm_values:
                for temp_acct in tm_values:

                    file_obj = (TopportunityPldFileAccounts.objects.filter(TemporaryAccountNumber=temp_acct,OpportunityPldFileSystemNumber__AnalyzerPacketSystemNumber=analyzer_id)
                                .select_related("OpportunityPldFileSystemNumber").first())
                    filename = (
                        file_obj.OpportunityPldFileSystemNumber.FileName
                        if file_obj else "-"
                    )

                    parent_data[temp_acct] = "Opportunity PLD"
                    subparent_data[temp_acct] = filename
                    accountname_data[temp_acct] = temp_acct
            
            df["Parent"] = df["BillToAccountNumber"].map(parent_data)
            df["SubParent"] = df["BillToAccountNumber"].map(subparent_data)
            df["AccountName"] = df["BillToAccountNumber"].map(accountname_data)
            df.rename(columns={'BillToAccountNumber':'Account'}, inplace=True)
            # Apply annualization factor per account: TM accounts use Opp PLD file factor, others use Historical PLD.
            df["_af"] = df["Account"].apply(
                lambda acct: get_annualization_factor(analyzer_id, account_number=acct)
            )
            df["TotalVolume"] = df["TotalVolume"] * df["_af"]
            # Weight = SUM(BW*PQ) and Zone = SUM(Zone*PQ) must also be annualized so that
            # dividing by annualized TotalVolume still yields the correct per-piece average.
            df["Weight"] = df["Weight"] * df["_af"]
            df["Zone"]   = df["Zone"]   * df["_af"]
            df.drop(columns=["_af"], inplace=True)
            grp_df=df.groupby(['Parent','SubParent'],as_index=False).agg({
                'ADV':'sum',
                'Weight':'sum',
                'Zone':'sum',
                'BaseGross':'sum',
                'BaseNet':'sum',
                'TotalVolume':'sum',
                'Shipments':'sum',
                'GrossRevenue':'sum',
                'NetRevenue':'sum',
                'TotalCost':'sum',
                'FreightCost':'sum'
            })
            # Individual Caluclations
            div_cols=['Zone','Weight']
            df[div_cols] = df[div_cols].div(df["TotalVolume"].replace(0, 1), axis=0).round(2)
            df['PPS']=df['TotalVolume'].div(df['Shipments'].replace(0, 1), axis=0).round(2)
            df['basedisc']=((df['BaseGross']-df['BaseNet'])*100).div(df['BaseGross'].replace(0, 1), axis=0).round(2)
            df['baserpp']=df['BaseNet'].div(df['TotalVolume'].replace(0, 1), axis=0).round(2)
            df['baseprofit']=(df['BaseNet']-df['FreightCost']).round(2)
            df['baseor']=df['FreightCost'].div(df['BaseNet'].replace(0, 1), axis=0).round(2)
            df['totaldisc']=((df['GrossRevenue'] - df['NetRevenue'])*100).div(df['GrossRevenue'].replace(0, 1), axis=0).round(2)
            df['totalrpp']=df['NetRevenue'].div(df['TotalVolume'].replace(0, 1), axis=0).round(2)
            df['totalprofit']=(df['NetRevenue'] - df['TotalCost']).round(2)
            df['totalor']=df['TotalCost'].div(df['NetRevenue'].replace(0, 1), axis=0).round(2)
            round_list=['ADV','BaseGross','BaseNet','GrossRevenue',
                        'NetRevenue','TotalCost','FreightCost']
            df[round_list]=df[round_list].round(2)
            df["TotalVolume"]=df["TotalVolume"].round(0)
            # Grouped Caluclations
            div_cols=['Zone','Weight']
            grp_df[div_cols] = grp_df[div_cols].div(grp_df["TotalVolume"].replace(0, 1), axis=0).round(2)
            grp_df['PPS']=grp_df['TotalVolume'].div(grp_df['Shipments'].replace(0, 1), axis=0).round(2)
            grp_df['basedisc']=((grp_df['BaseGross']-grp_df['BaseNet'])*100).div(grp_df['BaseGross'].replace(0, 1), axis=0).round(2)
            grp_df['baserpp']=grp_df['BaseNet'].div(grp_df['TotalVolume'].replace(0, 1), axis=0).round(2)
            grp_df['baseprofit']=(grp_df['BaseNet']-grp_df['FreightCost']).round(2)
            grp_df['baseor']=grp_df['FreightCost'].div(grp_df['BaseNet'].replace(0, 1), axis=0).round(2)
            grp_df['totaldisc']=((grp_df['GrossRevenue'] - grp_df['NetRevenue'])*100).div(grp_df['GrossRevenue'].replace(0, 1), axis=0).round(2)
            grp_df['totalrpp']=grp_df['NetRevenue'].div(grp_df['TotalVolume'].replace(0, 1), axis=0).round(2)
            grp_df['totalprofit']=(grp_df['NetRevenue'] - grp_df['TotalCost']).round(2)
            grp_df['totalor']=grp_df['TotalCost'].div(grp_df['NetRevenue'].replace(0, 1), axis=0).round(2)
            grp_df[round_list]=grp_df[round_list].round(2)
            dollar_cols=['GrossRevenue','NetRevenue','totalrpp','baserpp','baseprofit','totalprofit','BaseGross','BaseNet']
            for dc in dollar_cols:
                df[dc]=df[dc].apply(lambda x: f"$ {float(x):,.2f}")
                grp_df[dc]=grp_df[dc].apply(lambda x: f"$ {float(x):,.2f}")
            df[df.columns]=df[df.columns].astype(str)
            grp_df[grp_df.columns]=grp_df[grp_df.columns].astype(str)
            percent_cols=['basedisc','totaldisc']
            for pc in percent_cols:
                df[pc]=df[pc]+'%'
                grp_df[pc]=grp_df[pc]+'%'
            
            cols=['Zone','Weight','PPS','basedisc','baserpp','baseprofit','baseor',
                  'totaldisc','totalrpp','totalprofit','totalor','ADV','TotalVolume','BaseGross','BaseNet','GrossRevenue','NetRevenue','AccountName','Account']

            details = df.groupby(['Parent','SubParent']).apply(
                    lambda x: x[cols].to_dict('records')
                ).reset_index(name='details')
            join_cols=['Parent','SubParent','Zone','Weight','PPS','basedisc','baserpp','baseprofit','baseor',
                  'totaldisc','totalrpp','totalprofit','totalor','ADV','TotalVolume','BaseGross','BaseNet','GrossRevenue','NetRevenue']
    
            grp_df=grp_df[join_cols].merge(details,on=['Parent','SubParent'],how='left')
            data_list=grp_df.to_dict(orient='records')
            final_json=[{'Scenario':scenario_number,'data':data_list}]
            # final_json = json.loads(
            #     json.dumps(final)
            #     .replace("BillToAccountNumber", "Account")
            # )
            log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(
                        final_json,
                        status=status.HTTP_200_OK,
                    )
        except Exception as e:
                    import traceback
                    print(traceback.print_exc())
                    log_error(
                        "Shipping Profile Summary Account API GET Method failed",
                        context="ShippingProfileSummaryAccountAPIView.get - Exception encountered",
                        exc=e
                    )
                    log_info("Shipping Profile Summary Account API GET Method", context="Shipping Profile Summary Account API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                    log_error("Shipping Profile Summary Account API GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
                    return Response(
                        {"error": f"Something went wrong: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )




@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileSummaryAccessorialAPIView(APIView):
    allowed_methods = ["GET"]
    def get(self, request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Started")
            empId=request.claims['EmpID']
            log_info(
                "EmpID received",
                context="Shipping Profile Summary Accessorial API GET Method - EmpID",
                emp_id=empId
            )
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Summary Accessorial API GET Method", context=f"User Authentication : {empId}")
            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"Query : {user_number.query}")
            if not user_number:
                log_warning("Shipping Profile Summary Accessorial API GET Method", context=f"Not accessible. Emp Id:{empId}")
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error":"Inaccessible"},status=status.HTTP_400_BAD_REQUEST)
            analyzer_id = request.query_params.get("AnalyzerPacketID")
            scenario_system_number = request.query_params.get("ScenarioSystemNumber")
            bid_number = request.query_params.get("BidNumber", "All")
            acc_nums = request.query_params.get("AccountNumber", "All")
            svc_codes = request.query_params.get("ServiceCode", "All")
            costBasis = request.query_params.get("CostBasis")
            accessorial_codes=request.query_params.get("AccessorialCodes","All")
            servicefeaturetypecode=request.query_params.get("servicefeaturetypecode","all")
            if not servicefeaturetypecode:
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"Service Feature Type Code missing")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing servicefeaturetypecode"}, status=status.HTTP_400_BAD_REQUEST)
            # ----- Validate required inputs -----
            if not analyzer_id:
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"AnalyzerPacketID missing")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing AnalyzerPacketID"}, status=status.HTTP_400_BAD_REQUEST)
            if not scenario_system_number:
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"ScenarioSystemNumber missing")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing ScenarioSystemNumber"}, status=status.HTTP_400_BAD_REQUEST)
            if not costBasis:
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"CostBasis missing")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing CostBasis"}, status=status.HTTP_400_BAD_REQUEST)

            log_info(
                "AccessorialSummaryAPIView inputs captured",
                context="Shipping Profile Summary Accessorial API GET Method - Input parameters",
                analyzer_packet_id=analyzer_id,
                scenario_system_number=scenario_system_number,
                bid_number=bid_number,
                account_numbers=acc_nums,
                service_codes=svc_codes,
                cost_basis=costBasis
            )
            bid_number=bid_number.strip("'\"")
            acc_nums=acc_nums.strip("'\"")
            svc_codes=svc_codes.strip("'\"")
            accessorial_codes=accessorial_codes.strip("'\"")
            costBasis = costBasis.strip("'\"") 
            servicefeaturetypecode=servicefeaturetypecode.strip("'\"")
            if costBasis == "Fully Allocated Cost" or costBasis == "FullyAllocatedCost": 
                costBasis = "BaseBidCost" 
            elif costBasis == "Long Run Marginal Cost" or costBasis == "LongRunMarginalCost": 
                costBasis = "MarginalCost" 
            else: 
                return Response({"error": "Incorrect Cost Basis"}, status=status.HTTP_400_BAD_REQUEST)
            # print(costBasis)
            # ----- Step 1: Get bid info for this ScenarioSystemNumber -----
            bid_qs = (
                TAnalyzerScenarioBid.objects
                .filter(ScenarioSystemNumber=scenario_system_number)
                .values(
                    "ScenarioSystemNumber",
                    "ScenarioSystemNumber__ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber",
                )
            )
            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"Query : {str(bid_qs.query)}")
            if not bid_qs:
                log_error("Shipping Profile Summary Accessorial API GET Method", context=f"No bids found for Scenario System Number: {scenario_system_number}")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No bids found for given scenario"}, status=status.HTTP_400_BAD_REQUEST)

            bid_df = pd.DataFrame(bid_qs)
            bid_df.rename(
                columns={
                    "ScenarioSystemNumber__ScenarioNumber": "ScenarioNumber",
                    "ScenarioSystemNumber__SummaryGeneratedIndicator": "SummaryGeneratedIndicator",
                    "PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber": "BidNumber",
                },
                inplace=True,
            )
            bid_df["BidNumber"] = bid_df["BidNumber"].astype(str)
            # print(bid_df)
            bid_df["ScenarioNumber"] = bid_df.apply(
                lambda r: getScenarioHierarchy(r['ScenarioSystemNumber']) if not r["SummaryGeneratedIndicator"] else str(r["ScenarioNumber"]),
                axis=1,
            )
            # print(bid_df)
            bid_df["ScenarioNumber"] = bid_df["ScenarioNumber"].astype(str)
            
            bid_list = bid_number.split(",") if bid_number.lower() != "all" else ["All"]
            if bid_number.lower() == "all":
                bid_list = bid_df["BidNumber"].dropna().unique().tolist()
            else:
                bid_list = bid_number.split(",")
            scenario_number = str(bid_df['ScenarioNumber'].unique()[0])
            account_filter = ""
            accessorial_filter=""
            service_filter = ""
            servicefeaturetypecode_filter=""
            acc_nums = acc_nums.split(",") if acc_nums.lower() != "all" else ["All"]
            svc_codes = svc_codes.split(",") if svc_codes.lower() != "all" else ["All"]
            accessorial_list = accessorial_codes.split(",") if accessorial_codes.lower() != "all" else ["All"]
            servicefeaturetypecode_list=servicefeaturetypecode.split(",") if servicefeaturetypecode.lower()!="all" else ["All"]
            account_filter = " AND BillToAccountNumber IN (" + ",".join(f'"{x}"' for x in acc_nums) + ")" if "All" not in acc_nums else ""
            service_filter = " AND ServiceCode IN (" + ",".join(f'"{x}"' for x in svc_codes) + ")" if "All" not in svc_codes else ""
            accessorial_filter = " AND DMAccessorialType IN (" + ",".join(f'"{x}"' for x in accessorial_list) + ")" if "All" not in accessorial_list else ""
            bid_param = " AND BidNumber IN (" + ",".join(f'"{b}"' for b in bid_list) + ")" if "All" not in bid_list else ""
            servicefeaturetypecode_filter = " AND ServiceFeatureTypeCode IN (" + ",".join(f'"{x}"' for x in servicefeaturetypecode_list) + ")" if "All" not in servicefeaturetypecode_list else ""

            project_id = os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table_accessorial = os.getenv("TABLE_SUMMARY_ACCESSORIAL")  
            accessorial_summary = f"`{project_id}.{dataset}.{table_accessorial}`"


            query = f"""
                    WITH base AS (
                    SELECT


                        BillToAccountNumber,

                        AccessorialServiceTypeCode,
                        DMAccessorialGroup,
                        DMAccessorialType,
                        ServiceCode,
                        SUM(PackageQuantity) AS PackageQuantity,
                        SUM(AccessorialQuantity) AS AccessorialQuantity,
                        SUM(ADU) AS ADU,
                        SUM(AccessorialGrossCharge) AS AccessorialGrossCharge,
                        SUM(AccessorialNetCharge) AS AccessorialNetCharge,
                        SUM(BaseBidCost) AS BaseBidCost,
                        SUM(MarginalCost) AS MarginalCost,
                        SUM({costBasis}) AS TotalCost
                    FROM {accessorial_summary}
                    WHERE AnalyzerPacketID = '{analyzer_id}'
                      AND ScenarioNumber = '{scenario_number}'
                      {bid_param}
                      {account_filter}
                      {service_filter}
                      {servicefeaturetypecode_filter}
                      {accessorial_filter}
                    GROUP BY

                        BillToAccountNumber,

                        AccessorialServiceTypeCode,
                        DMAccessorialGroup,
                        DMAccessorialType,
                        ServiceCode
                ),
                total_pkg AS (


                select AccessorialServiceTypeCode,sum(PackageQuantity) as TotalDistinctPackageQuantity
                    FROM {accessorial_summary}

                    WHERE AnalyzerPacketID = '{analyzer_id}'
                      AND ScenarioNumber = '{scenario_number}'
                      
                        {bid_param}
                      {account_filter}
                      {service_filter}
                      {servicefeaturetypecode_filter}
                      {accessorial_filter}

                      group by AccessorialServiceTypeCode
                )
                SELECT b.*, t.TotalDistinctPackageQuantity
                FROM base as b join 
                total_pkg as t on b.AccessorialServiceTypeCode=t.AccessorialServiceTypeCode

                
            """
            project_id = os.getenv("PROJECT_ID")
            dataset = os.getenv("GCPR_SUMMARY_DATABASE")
            table = os.getenv("TABLE_SUMMARY_SHIPPING_PROFILE")
            query2=f"""
            select sum(PackageQuantity*AnnualizationFactor) as pack
            FROM `{project_id}.{dataset}.{table}`
            where AnalyzerPacketID='{analyzer_id}' and
            ScenarioNumber='{scenario_number}'

            """
            job = client.query(query2)
            result_summ = job.result()
            row = list(result_summ)[0]
            package_sum = row.pack if row.pack is not None else 0

            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"BigQuery : {query2}")

            if package_sum==0 or package_sum is None:
                log_info("Shipping Profi'le Summary Accessorial API GET Method", context=f"BigQuery : {query2}")
                return Response(
                    {"message": "Package quantity sum is  found 0 the selected filters"},
                    status=status.HTTP_200_OK,
                )

            # Extract the single value
            
            # print(query)
            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"BigQuery : {query}")
            log_info(
                "Executing Accessorial BigQuery",
                context="Shipping Profile Summary Accessorial API GET Method - BigQuery execution"
            )
            result_rows = client.query(query).result()
            result_data = [dict(row.items()) for row in result_rows]
            if not result_data:
                log_info("Shipping Profile Summary Accessorial API GET Method", context=f"No accessorial data found for the provided filters from BigQuery")
                log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response(
                    {"message": "No accessorial data found for the selected filters"},
                    status=status.HTTP_200_OK,
                )

            big_df = pd.DataFrame(result_data)
            hier_qs = TAccessorialHierarchy.objects.values(
                "AccessorialServiceTypeCode",
                "AccessorialServiceGroupName",
                "AccessorialServiceSubgroupName",
                "AccessorialServiceDetailText",
            )
            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"Query : {str(hier_qs.query)}")
            hier_df = pd.DataFrame(hier_qs)
            if not hier_df.empty and "AccessorialServiceTypeCode" in big_df.columns:
                big_df = big_df.merge(
                    hier_df,
                    on="AccessorialServiceTypeCode",
                    how="left",
                )
            else:
                big_df["AccessorialServiceGroupName"] = ""
                big_df["AccessorialServiceSubgroupName"] = ""
                big_df["AccessorialServiceDetailText"] = ""
            # print(hier_df)
            srv_qs = TServiceHierarchy.objects.values(
                "PricingCoreServiceCode",
                "PricingCoreServiceCodeDescriptionText",
            ).distinct()
            log_debug("Shipping Profile Summary Accessorial API GET Method", context=f"Query : {str(srv_qs.query)}")
            srv_df = pd.DataFrame(srv_qs)
            if not srv_df.empty:
                srv_df = srv_df.rename(
                    columns={
                        "PricingCoreServiceCode": "ServiceCode",
                        "PricingCoreServiceCodeDescriptionText": "ServiceDescription"
                    }
                )
                big_df = big_df.merge(srv_df, on="ServiceCode", how="left")
            else:
                big_df["ServiceDescription"] = big_df["ServiceCode"]


            big_df["PackageQuantity"] = big_df["PackageQuantity"].astype(float)
            big_df["AccessorialQuantity"] = big_df["AccessorialQuantity"].astype(float)
            big_df["AccessorialGrossCharge"] = big_df["AccessorialGrossCharge"].astype(float)
            big_df["AccessorialNetCharge"] = big_df["AccessorialNetCharge"].astype(float)
            big_df["ADU"] = big_df["ADU"].astype(float)
            big_df["BaseBidCost"] = big_df["BaseBidCost"].astype(float)
            big_df["MarginalCost"] = big_df["MarginalCost"].astype(float)
            big_df["TotalCost"] = big_df["TotalCost"].astype(float)
            big_df["TotalDistinctPackageQuantity"] = big_df["TotalDistinctPackageQuantity"].astype(float)

            # Apply per-row AF BEFORE re-aggregating to handle mixed HPLD/OPLD data correctly.
            big_df["_af"] = big_df["BillToAccountNumber"].apply(
                lambda acct: get_annualization_factor(analyzer_id, account_number=str(acct))
            )
            big_df["PackageQuantity"]       = big_df["PackageQuantity"]       * big_df["_af"]
            big_df["AccessorialQuantity"]   = big_df["AccessorialQuantity"]   * big_df["_af"]
            # TotalDistinctPackageQuantity is per-AccessorialServiceTypeCode from total_pkg CTE;
            # annualize it with a blended AF (volume-weighted across accounts for that row's code).
            _af_map = big_df.groupby("BillToAccountNumber")["PackageQuantity"].sum()
            _total  = float(_af_map.sum())
            _blended_af = (
                float(sum(get_annualization_factor(analyzer_id, account_number=str(a)) * float(q)
                          for a, q in _af_map.items()) / _total)
                if _total > 0 else 1.0
            )
            big_df["TotalDistinctPackageQuantity"] = big_df["TotalDistinctPackageQuantity"] * _blended_af
            # Re-aggregate to drop BillToAccountNumber axis
            _a_num_cols = ["PackageQuantity", "AccessorialQuantity", "ADU",
                           "AccessorialGrossCharge", "AccessorialNetCharge",
                           "BaseBidCost", "MarginalCost", "TotalCost",
                           "TotalDistinctPackageQuantity"]
            _a_grp_cols = [c for c in big_df.columns
                           if c not in _a_num_cols + ["BillToAccountNumber", "_af"]]
            big_df = big_df.groupby(_a_grp_cols, as_index=False, dropna=False)[_a_num_cols].sum()


            grp_cols = [
                "AccessorialServiceGroupName",
                "AccessorialServiceSubgroupName",
                "AccessorialServiceDetailText",
            ]
            for c in grp_cols:
                if c not in big_df.columns:
                    big_df[c] = ""

            # Denominator computed in BigQuery: SUM of PackageQuantity grouped by ServiceCode first,
            # so each service is counted once regardless of how many accessorial-type rows it has.
            # total_pkg_qty = big_df["TotalDistinctPackageQuantity"].iloc[0]
            # total_pkg_qty = big_df["PackageQuantity"].iloc[0]
            # if total_pkg_qty == 0:
            #     total_pkg_qty = 1

            # TotalPackages per group: deduplicate by (grp_cols + ServiceCode) so a service's
            # packages are counted only once per group, not once per accessorial type.
            pkg_per_group = (
                big_df.drop_duplicates(subset=grp_cols + ["ServiceCode"])
                .groupby(grp_cols, dropna=False)["PackageQuantity"]
                .sum()
                .reset_index()
                .rename(columns={"PackageQuantity": "TotalPackages"})
            )

            grouped = big_df.groupby(grp_cols, dropna=False).agg(
                TotalUnits=("AccessorialQuantity", "sum"),
                TotalPackageQuantity=("PackageQuantity", "sum"),
                ADU=("ADU", "sum"),
                GrossRevenue=("AccessorialGrossCharge", "sum"),
                NetRevenue=("AccessorialNetCharge", "sum"),
                TotalCost=("TotalCost", "sum"),
            ).reset_index()
            grouped = grouped.merge(pkg_per_group, on=grp_cols, how="left")
            rpp_units_safe = grouped["TotalUnits"].replace(0, 1)
            gross_safe = grouped["GrossRevenue"].replace(0, 1)
            net_safe = grouped["NetRevenue"].replace(0, 1)
            grouped["Discount"] = (grouped["GrossRevenue"] - grouped["NetRevenue"]).div(gross_safe).mul(100)
            grouped["GrossRPP"] = grouped["GrossRevenue"].div(rpp_units_safe)
            grouped["NetRPP"] = grouped["NetRevenue"].div(rpp_units_safe)
            grouped["Profit"] = grouped["NetRevenue"] - grouped["TotalCost"]
            # grouped["OR"] = grouped["TotalCost"].div(net_safe)
            grouped["OR"] = grouped.apply(lambda r: r["TotalCost"] / r["NetRevenue"] if r["NetRevenue"] != 0 else None,axis=1)

            # NEW TotalVolume formula: SUM(AccessorialQuantity) / SUM(PackageQuantity)
            # grouped already contains TotalUnits and TotalPackages
            grouped["TotalPackages"] = grouped["TotalPackages"].replace(0, 1)  # avoid divide-by-zero
            pkg_qty=grouped['TotalPackageQuantity'].replace(0, 1)
            grouped["TotalVolume"] = grouped["TotalUnits"].div(package_sum).mul(100)

            # grouped["TotalVolume"] = grouped["TotalUnits"].div(total_pkg_qty).mul(100)
            big_df.rename(columns={ 'AccessorialQuantity': 'TotalUnits', 
              'AccessorialGrossCharge': 'GrossRevenue', 'AccessorialNetCharge': 'NetRevenue'},inplace=True)
            srv_rpp_units_safe = big_df["TotalUnits"].replace(0, 1)
            srv_gross_safe = big_df["GrossRevenue"].replace(0, 1)
            srv_net_safe = big_df["NetRevenue"].replace(0, 1)
            big_df["Discount"] = (big_df["GrossRevenue"] - big_df["NetRevenue"]).div(srv_gross_safe).mul(100)
            big_df["GrossRPP"] = big_df["GrossRevenue"].div(srv_rpp_units_safe)
            big_df["NetRPP"] = big_df["NetRevenue"].div(srv_rpp_units_safe)
            big_df["Profit"] = big_df["NetRevenue"] - big_df["TotalCost"]
            # big_df["OR"] = big_df["TotalCost"].div(srv_net_safe)
            big_df["OR"] = big_df.apply(lambda r: r["TotalCost"] / r["NetRevenue"] if r["NetRevenue"] != 0 else None,axis=1)

            # NEW TotalVolume formula at service level
            big_df["PackageQuantity"] = big_df["PackageQuantity"].replace(0, 1)  # avoid divide-by-zero
            total_pkg_qty=big_df['TotalDistinctPackageQuantity'].replace(0,1)
            big_df["TotalVolume"] = big_df["TotalUnits"].div(package_sum).mul(100)  
            
            def fmt(x, pattern):
                if pattern == "1f":
                    return float(f"{x:.1f}")
                if pattern == "2f":
                    return float(f"{x:.2f}")
                if pattern == "int":
                    return int(round(float(x)))
                return x

            format_rules = {
                "int": ["GrossRevenue", "NetRevenue", "Profit"],
                "1f": ["Discount", "TotalVolume", "ADU"],
                "2f": ["GrossRPP", "NetRPP", "OR"],
            }

            for df in [grouped, big_df]:
                for pattern, columns in format_rules.items():
                    for col in columns:
                        if col in df.columns:
                            df[col] = df[col].apply(
                                lambda x: fmt(x, pattern) if pd.notnull(x) else x
                            )
            dollars=['GrossRevenue','NetRevenue','GrossRPP','NetRPP','Profit']
            for dc in dollars:
                big_df[dc]=big_df[dc].apply(lambda x: f"$ {float(x):,.2f}")
                grouped[dc]=grouped[dc].apply(lambda x: f"$ {float(x):,.2f}")
            
            big_df[big_df.columns]=big_df[big_df.columns].astype(str)
            grouped[grouped.columns]=grouped[grouped.columns].astype(str)
            percent_cols=['Discount','TotalVolume']
            
            for pc in percent_cols:
                big_df[pc]=big_df[pc]+'%'
                grouped[pc]=grouped[pc]+'%'
            for df in [grouped, big_df]:
                df["OR"] = df["OR"].apply(lambda x: "N/A" if x=='None' else x)

            join_cols=['AccessorialServiceGroupName','AccessorialServiceSubgroupName','AccessorialServiceDetailText',
                       'TotalUnits','TotalVolume','ADU','GrossRevenue','NetRevenue','Discount','GrossRPP','NetRPP','Profit','OR'] 
            
            cols=['ServiceDescription','TotalUnits','TotalVolume','ADU','GrossRevenue','NetRevenue','Discount','GrossRPP','NetRPP','Profit','OR']
            details = big_df.groupby(grp_cols).apply(
                    lambda x: x[cols].to_dict('records')
                ).reset_index(name='details')
            grouped=grouped[join_cols].merge(details,on=grp_cols,how='left')
            data_list=grouped.to_dict(orient='records')
            final=[{'Scenario':scenario_number,'data':data_list}]
            final_json = json.loads(
                json.dumps(final)
                .replace("AccessorialServiceGroupName", "AccessorialType")
                .replace("AccessorialServiceSubgroupName", "AccessorialGroup")
                .replace("AccessorialServiceDetailText", "AccessorialDetail")
                .replace("ServiceDescription", "Service")
            )
            log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(
                        final_json,
                        status=status.HTTP_200_OK,
                    )
        except Exception as e:
            import traceback
            # print(traceback.print_exc())
            log_error(
                "Shipping Profile Summary Accessorial API GET Method failed",
                context="ShippingProfileSummaryAccessorialAPIView.get - Exception encountered",
                exc=e
            )
            log_info("Shipping Profile Summary Accessorial API GET Method", context="Shipping Profile Summary Accessorial API GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            log_error("Shipping Profile Summary Accessorial API GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
            return Response(
                {"error": f"Something went wrong: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )




@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileFiltersAPI_Filter1(APIView):
    allowed_methods = ['GET']
    def get(self, request):
        start_time= time.time()
        try:
            log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Started")
            empId=request.claims['EmpID']
            log_info(
                "Shipping Profile Filters API Filter1 GET Method",
                context=f"Received EmpID: '{empId}'"
            )
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"User Authentication : {empId}")
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"Query : {user_number.query}")
            if not user_number:
                log_warning("Shipping Profile Filters API Filter1 GET Method", context=f"Not accessible. Emp Id:{empId}")
                log_error("Shipping Profile Filters API Filter1 GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error":"Inaccessible"},status=status.HTTP_400_BAD_REQUEST)
            analyzer_packet_system_number = request.GET.get('AnalyzerPacketSystemNumber')
            if not analyzer_packet_system_number:
                log_error("Shipping Profile Filters API Filter1 GET Method", context=f"AnalyzerPacketSystemNumber missing")
                log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing AnalyzerPacketSystemNumber"}, status=status.HTTP_400_BAD_REQUEST)
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber__AnalyzerPacketSystemNumber=analyzer_packet_system_number
                                     ).values(
                        'ScenarioSystemNumber',
                        'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber',
                        'AnalyzerBidName'
                    )
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"Query : {str(bid_info.query)}")
            scee_bid=TScenario.objects.filter(AnalyzerPacketSystemNumber=analyzer_packet_system_number).values('ScenarioName','ScenarioSystemNumber','SummaryGeneratedIndicator','ScenarioNumber')
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"Query : {str(scee_bid.query)}")
            if not scee_bid:
                log_error("Shipping Profile Filters API Filter1 GET Method", context=f"No scenarios found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No scenario found for given scenario system number"}, status=status.HTTP_400_BAD_REQUEST)
            scee_bid_df=pd.DataFrame(scee_bid)
            if not bid_info:
                log_error("Shipping Profile Filters API Filter1 GET Method", context=f"No bids found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No bids found for given scenario"}, status=status.HTTP_400_BAD_REQUEST)
            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(columns={
                'ScenarioSystemNumber__ScenarioName': 'ScenarioName',
                'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber',
                'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber'
            }, inplace=True)
            scee_bid_df['TempScenarioNumber'] = scee_bid_df.apply(
                lambda r: getScenarioHierarchy(r['ScenarioSystemNumber']) if not r['SummaryGeneratedIndicator'] else str(r['ScenarioNumber']),
                axis=1
            )
            # query=f"""SELECT
            #         distinct BidNumber,ScenarioNumber as TempScenarioNumber
            #         FROM {shipping_profile_summary} where AnalyzerPacketID='{analyzer_packet_system_number}'"""
            query = f"""
                SELECT DISTINCT ScenarioNumber, BidNumber 
                FROM {shipping_profile_summary}
                WHERE AnalyzerPacketID='{analyzer_packet_system_number}'
                UNION DISTINCT
                SELECT DISTINCT ScenarioNumber, BidNumber 
                FROM {accessorial_summary}
                WHERE AnalyzerPacketID='{analyzer_packet_system_number}'
                """
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"BigQuery : {query}")
            result_service=client.query(query=query).to_dataframe()
            if result_service.empty:
                log_info("Shipping Profile Filters API Filter1 GET Method", context=f"No scenario-bid mapping data found in BigQuery for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data found for the selected scenarios"}, status=status.HTTP_200_OK)
            result_service.rename(columns={'ScenarioNumber': 'TempScenarioNumber'}, inplace=True)
            scee_bid_df['TempScenarioNumber']=scee_bid_df['TempScenarioNumber'].astype(str)
            result_service['TempScenarioNumber']=result_service['TempScenarioNumber'].astype(str)
            merged_df=pd.merge(scee_bid_df[['ScenarioSystemNumber','TempScenarioNumber','ScenarioName']], result_service,on=['TempScenarioNumber'], how='inner')
            merged_df = pd.merge(merged_df, bid_df,on=['ScenarioSystemNumber','BidNumber'], how='left')
            merged_df.loc[merged_df['BidNumber'].astype(str).str.startswith('99'), 'AnalyzerBidName'] = 'Unincented PLD'
            final_json = {"Scenario": []}
            merged_df=merged_df.astype(str)
            for scenario, df_scn in merged_df.groupby("ScenarioSystemNumber"):
                scenario_block = {
                    "ScenarioSystemNumber": str(scenario),
                    "ScenarioName": df_scn["ScenarioName"].iloc[0],
                    "Bid": []
                }
                for _, row in df_scn.iterrows():
                    bidname=''
                    if str(row["BidNumber"]).startswith('99'):
                        bidname="Unincented PLD"
                    else:
                        bidname=row['AnalyzerBidName']

                    scenario_block["Bid"].append({
                        "BidNumber": row["BidNumber"],
                        "BidName": bidname
                    })

                final_json["Scenario"].append(scenario_block)
            log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            log_info("Shipping Profile Filters API Filter1 GET Method", context=f"Final JSON: {final_json}")
            return Response(final_json, status=status.HTTP_200_OK)
        except Exception as e:
            import traceback
            print(traceback.print_exc())
            log_error("Shipping Profile Filters API Filter1 GET Method", context=f"Exception occurred: {str(e)}")
            log_info("Shipping Profile Filters API Filter1 GET Method", context="Shipping Profile Filters API Filter1 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            log_error("Shipping Profile Filters API Filter1 GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)



@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileFiltersAPI_Filter2(APIView):
    def get(self, request):
        start_time=time.time()
        try:
            log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Started")
            empId=request.claims['EmpID']
            log_info(
                "Shipping Profile Filters API Filter2 GET Method",
                context=f"Received EmpID: '{empId}'"
            )
            user_number =TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Filters API Filter2 GET Method", context=f"User Authentication : {empId}")
            log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"Query : {user_number.query}")
            if not user_number:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                log_warning("Shipping Profile Filters API Filter2 GET Method", context=f"Not accessible. Emp Id:{empId}")
                return Response({"error":"Inaccessible"},status=status.HTTP_400_BAD_REQUEST)
            analyzer_packet_system_number = request.GET.get('AnalyzerPacketSystemNumber')
            scenario_number = request.GET.get('ScenarioNumber')
            bid_numbers = request.GET.get('BidNumber')
            if not analyzer_packet_system_number:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"AnalyzerPacketSystemNumber missing")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing AnalyzerPacketSystemNumber"}, status=status.HTTP_400_BAD_REQUEST)
            if not scenario_number:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"ScenarioNumber missing")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing ScenarioNumber"}, status=status.HTTP_400_BAD_REQUEST)
            if not bid_numbers:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"BidNumber missing")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing BidNumber"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                bid_numbers=tuple(bid_numbers.split(','))
            except Exception:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"Error processing Bid Numbers: {bid_numbers}")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': f'Error processing Bid Numbers {bid_numbers}'}, status=status.HTTP_400_BAD_REQUEST)
            scenarios = ( TAnalyzerScenarioBid.objects.filter( 
                ScenarioSystemNumber__AnalyzerPacketSystemNumber=analyzer_packet_system_number, 
                ScenarioSystemNumber=scenario_number)\
                .values( 'ScenarioSystemNumber', 
                        'ScenarioSystemNumber__ScenarioName', 
                        'ScenarioSystemNumber__ScenarioNumber', 
                        'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber', 
                        'AnalyzerBidName', 
                        'ScenarioSystemNumber__SummaryGeneratedIndicator' ) )
            log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"Query : {str(scenarios.query)}")
            scenario_df = pd.DataFrame(scenarios) 
            if scenario_df.empty:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"No scenario-bid data found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}, ScenarioNumber: {scenario_number}, BidNumbers: {bid_numbers}")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': 'No scenario-bid data found for given inputs'}, status=status.HTTP_404_NOT_FOUND)
            scenario_df.rename(columns={
                 'ScenarioSystemNumber__ScenarioName': 'Name', 
                 'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber', 
                 'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber',
                   'AnalyzerBidName': 'BidName', 
                   'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator' }, inplace=True)
            scenario_number=scenario_df['ScenarioNumber'].unique()[0]
            # query = f"""
            #     SELECT ScenarioNumber, BidNumber, BillToAccountNumber,
            #            MovementDirectionCode, Mode, ServiceCode, ServiceFeatureTypeCode
            #     FROM {shipping_profile_summary}
            #     WHERE AnalyzerPacketID='{analyzer_packet_system_number}' and ScenarioNumber='{scenario_number}' and bidNumber in ({','.join([f"'{b}'" for b in bid_numbers])})
            # """
            query = f"""
                WITH svc AS (
                SELECT DISTINCT BillToAccountNumber, ServiceCode, ServiceFeatureTypeCode, MovementDirectionCode, Mode, ScenarioNumber, BidNumber
                FROM {shipping_profile_summary}
                WHERE AnalyzerPacketID='{analyzer_packet_system_number}' 
                AND ScenarioNumber='{scenario_number}' 
                AND BidNumber IN ({','.join([f"'{b}'" for b in bid_numbers])})
                ),
                asy AS (
                SELECT DISTINCT BillToAccountNumber, ServiceCode, ServiceFeatureTypeCode, DMAccessorialType 
                FROM {accessorial_summary} 
                WHERE AnalyzerPacketID='{analyzer_packet_system_number}' 
                AND ScenarioNumber='{scenario_number}' 
                AND BidNumber IN ({','.join([f"'{b}'" for b in bid_numbers])})
                )
                SELECT COALESCE(svc.BillToAccountNumber, asy.BillToAccountNumber) AS BillToAccountNumber, 
                COALESCE(svc.ServiceCode, asy.ServiceCode) AS ServiceCode, 
                COALESCE(svc.ServiceFeatureTypeCode, asy.ServiceFeatureTypeCode) AS ServiceFeatureTypeCode, 
                asy.DMAccessorialType,
                svc.MovementDirectionCode,
                svc.Mode,
                svc.ScenarioNumber, svc.BidNumber
                FROM svc FULL OUTER JOIN asy 
                ON svc.BillToAccountNumber=asy.BillToAccountNumber 
                AND svc.ServiceCode=asy.ServiceCode 
                AND svc.ServiceFeatureTypeCode=asy.ServiceFeatureTypeCode
            """
            log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"BigQuery : {query}")
            df = client.query(query).to_dataframe()
            if df.empty:
                log_error("Shipping Profile Filters API Filter2 GET Method", context=f"No data found in ShippingProfileFilters for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}, ScenarioNumber: {scenario_number}, BidNumbers: {bid_numbers}")
                log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({'error': 'No data found in ShippingProfileFilters'}, status=status.HTTP_404_NOT_FOUND)
            PROJECT_ID=os.getenv("PROJECT_ID")
            CIDH_DATASET_ID=os.getenv("CIDH_DATASET_ID")
            CIDH_BIGQUERY_VIEW=os.getenv("CIDH_BIGQUERY_VIEW")

            bill_to_list = df["BillToAccountNumber"].unique().tolist()
            query2 = f"""
                    SELECT AccountNumber, AccountName, ParentMdmIdNumber, EstatCustomerNumber
                    FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                    WHERE AccountHierarchyLevelCode='AD'
                    AND AccountNumber IN ({','.join([f"'{x}'" for x in bill_to_list])})
                    """
            log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"BigQuery : {query2}")
            df2 = client.query(query2).to_dataframe()

            parent_data = {}
            subparent_data = {}
            accountname_data = {}

            if not df2.empty:
                parent_mdm_ids = (
                    df2["ParentMdmIdNumber"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                )
                parent_mdm_ids = [x for x in parent_mdm_ids.tolist() if x and x.lower() != "nan"]

                hierarchy_by_estat = {}
                if parent_mdm_ids:
                    parent_ids_sql = ",".join([f"'{x}'" for x in set(parent_mdm_ids)])
                    query3 = f"""
                    SELECT EstatCustomerNumber, AccountName, ParentMdmIdNumber, AccountHierarchyLevelCode
                    FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                    WHERE EstatCustomerNumber IN ({parent_ids_sql})
                    """
                    log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"BigQuery : {query3}")
                    df3 = client.query(query3).to_dataframe()
                    if not df3.empty:
                        df3 = df3.drop_duplicates(subset=["EstatCustomerNumber"], keep="first")
                        hierarchy_by_estat = {
                            str(row["EstatCustomerNumber"]): row
                            for _, row in df3.iterrows()
                        }

                ac_parent_ids = set()
                for hierarchy_row in hierarchy_by_estat.values():
                    if hierarchy_row.get("AccountHierarchyLevelCode") == "AC":
                        ac_parent_id = hierarchy_row.get("ParentMdmIdNumber")
                        if pd.notna(ac_parent_id):
                            ac_parent_id = str(ac_parent_id).strip()
                            if ac_parent_id and ac_parent_id.lower() != "nan":
                                ac_parent_ids.add(ac_parent_id)

                ab_parent_name_map = {}
                if ac_parent_ids:
                    ab_parent_ids_sql = ",".join([f"'{x}'" for x in ac_parent_ids])
                    query4 = f"""
                    SELECT EstatCustomerNumber, AccountName
                    FROM `{PROJECT_ID}.{CIDH_DATASET_ID}.{CIDH_BIGQUERY_VIEW}`
                    WHERE EstatCustomerNumber IN ({ab_parent_ids_sql})
                    AND AccountHierarchyLevelCode='AB'
                    """
                    log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"BigQuery : {query4}")
                    df4 = client.query(query4).to_dataframe()
                    if not df4.empty:
                        df4 = df4.drop_duplicates(subset=["EstatCustomerNumber"], keep="first")
                        ab_parent_name_map = {
                            str(row["EstatCustomerNumber"]): row["AccountName"]
                            for _, row in df4.iterrows()
                        }

                for _, row in df2.iterrows():
                    acct = row["AccountNumber"]
                    accountname = row["AccountName"]
                    raw_parent_id = row["ParentMdmIdNumber"]

                    parent_name = "No Parent"
                    sub_parent_name = "No Sub Parent"

                    if pd.notna(raw_parent_id):
                        parent_id = str(raw_parent_id).strip()
                        if parent_id and parent_id.lower() != "nan":
                            hierarchy_row = hierarchy_by_estat.get(parent_id)
                            if hierarchy_row is not None:
                                level = hierarchy_row.get("AccountHierarchyLevelCode")
                                name = hierarchy_row.get("AccountName")
                                parent_of_parent_id = hierarchy_row.get("ParentMdmIdNumber")

                                if level == "AB":
                                    parent_name = name
                                elif level == "AC":
                                    sub_parent_name = name
                                    if pd.notna(parent_of_parent_id):
                                        parent_of_parent_id = str(parent_of_parent_id).strip()
                                        if parent_of_parent_id and parent_of_parent_id.lower() != "nan":
                                            parent_name = ab_parent_name_map.get(parent_of_parent_id, "No Parent")

                    parent_data[acct] = parent_name
                    subparent_data[acct] = sub_parent_name
                    accountname_data[acct] = accountname
            tm_values = [b for b in bill_to_list if b.startswith("TM")]
            if tm_values:
                for temp_acct in tm_values:

                    file_obj = (TopportunityPldFileAccounts.objects.filter(TemporaryAccountNumber=temp_acct,OpportunityPldFileSystemNumber__AnalyzerPacketSystemNumber=analyzer_packet_system_number)
                                .select_related("OpportunityPldFileSystemNumber").first())
                    filename = (
                        file_obj.OpportunityPldFileSystemNumber.FileName
                        if file_obj else "-"
                    )

                    parent_data[temp_acct] = "Opportunity PLD"
                    subparent_data[temp_acct] = filename
                    accountname_data[temp_acct] = temp_acct
            
            df["Parent"] = df["BillToAccountNumber"].map(parent_data)
            df["SubParent"] = df["BillToAccountNumber"].map(subparent_data)
            df["AccountName"] = df["BillToAccountNumber"].map(accountname_data)
            movement=TServiceHierarchy.objects\
                                .values( "MovementDirectionName","PricingCoreServiceCode", "PricingCoreServiceCodeDescriptionText","PricingDeliveryModeName").distinct()
            
            movement_df = pd.DataFrame(movement)
            df=df.merge(movement_df,left_on=['ServiceCode'], right_on=['PricingCoreServiceCode'], how='left')
            df.rename(columns={'MovementDirectionName':'MovementDirectionCode',
                               'PricingDeliveryModeName':'Mode',
                               'PricingCoreServiceCodeDescriptionText':'ServiceCodeName'}, inplace=True)
            # Preserve the natural TServiceHierarchy table order (by ServiceHierarchySystemNumber)
            # for the ServiceCode sequence, so the filter dropdown matches SELECT * ordering.
            service_order = list(dict.fromkeys(
                TServiceHierarchy.objects
                .order_by("ServiceHierarchySystemNumber")
                .values_list("PricingCoreServiceCode", flat=True)
            ))
            service_rank = {code: idx for idx, code in enumerate(service_order)}
            df["_svc_order"] = df["ServiceCode"].map(service_rank).fillna(len(service_rank)).astype(int)
            
            scenario_df['ScenarioNumber']=scenario_df['ScenarioNumber'].apply(str)
            scenario_df['ScenarioSystemNumber']=scenario_df['ScenarioSystemNumber'].apply(str)
            df = df.merge(
                scenario_df[['ScenarioSystemNumber','Name','ScenarioNumber','BidNumber',
                             'BidName']],
                on=['ScenarioNumber','BidNumber'],
                how='left'
            )
            mapping_qs = TPricingServiceFeatureMapping.objects.values(
                "ServiceFeatureTypeCode", "ServiceFeatureTypeCodeDescription"
            )
            log_debug("Shipping Profile Filters API Filter2 GET Method", context=f"Query : {str(mapping_qs.query)}")
            mapping_dict = {row["ServiceFeatureTypeCode"]: row["ServiceFeatureTypeCodeDescription"] for row in mapping_qs}
            df["ServiceFeatureTypeCodeDescription"] = df["ServiceFeatureTypeCode"].map(mapping_dict)
            final_json = []
            df = df.sort_values("_svc_order", kind="stable")
            df = df.astype(str)
            df2 = df2.astype(str)
            scenario_df = scenario_df.astype(str)
            for acct, df_acct in df.groupby("BillToAccountNumber"):
                account_block = {
                    "AccountNumber": acct,
                    "AccountName": df_acct["AccountName"].iloc[0],
                    "ParentName": df_acct["Parent"].iloc[0],
                    "SubParentName": df_acct["SubParent"].iloc[0],
                    "ServiceLevel": []
                }
                for svc, df_svc in df_acct.groupby("ServiceCode", sort=False):
                    service_level = {
                        "Movement": df_svc["MovementDirectionCode"].iloc[0],
                        "Mode": df_svc["Mode"].iloc[0],
                        "Service": df_svc["ServiceCodeName"].iloc[0],
                        "ServiceCode": df_svc["ServiceCode"].iloc[0], 
                        # Global rank from TServiceHierarchy so the UI can order services
                        # consistently even when they first appear in different accounts.
                        "ServiceOrder": int(float(df_svc["_svc_order"].iloc[0])),
                        "AccessorialLevel": []
                    }
                    service_types = []
                    if not df_svc.empty:
                        service_type_set = set()
                        for _, r in df_svc.iterrows():
                            code = r["ServiceFeatureTypeCode"]
                            desc = r["ServiceFeatureTypeCodeDescription"]
                            if desc in ["nan", "NaN", None]:
                                desc = None
                            service_type_set.add((code, desc))
                        service_types = [
                            {
                                "ServiceFeatureTypeCode": code,
                                "ServiceFeatureTypeDescription": desc,
                            }
                            for code, desc in service_type_set
                        ]

                    accessorial_names=['Other Charges','Transportation Charges','Pickup and Delivery','Returns','Fuel Surcharge','Custom Brokerage']
                    # accessorial_names=df_svc['DMAccessorialType'].unique().tolist()
                    for acc_name in accessorial_names:
                        accessorial_block = {"AccessorialName": acc_name, "ServiceType": service_types}
                        service_level["AccessorialLevel"].append(accessorial_block)
                    account_block["ServiceLevel"].append(service_level)
                final_json.append(account_block)
            log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(final_json, status=status.HTTP_200_OK)
        except Exception as e:
            import traceback
            log_error("Shipping Profile Filters API Filter2 GET Method", context=f"Exception occurred: {str(e)}")
            log_info("Shipping Profile Filters API Filter2 GET Method", context="Shipping Profile Filters API Filter2 GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            log_error("Shipping Profile Filters API Filter2 GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)




@method_decorator(azure_token_required,name='dispatch')
class ShippingProfileFiltersAPI_Filter1_NoBQ(APIView):
    allowed_methods = ['GET']
    def get(self, request):
        start_time = time.time()
        try:
            log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Started")
            empId=request.claims['EmpID']
            #logger.info(f"Received EmpID: '{empId}'")
            user_number = TUserProfile.objects.filter(CloudUserIdentificationNumber=empId)
            log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"User Authentication : {empId}")
            log_debug("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"Query : {user_number.query}")
            if not user_number:
                #logger.warning(f"Not accessible. Emp Id:{empId}")
                log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"User not found for EmpID: {empId}")
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Inaccessible"}, status=status.HTTP_400_BAD_REQUEST)
            analyzer_packet_system_number = request.GET.get('AnalyzerPacketSystemNumber')
            if not analyzer_packet_system_number:
                log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"AnalyzerPacketSystemNumber missing")
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "Missing AnalyzerPacketSystemNumber"}, status=status.HTTP_400_BAD_REQUEST)
            bid_info = TAnalyzerScenarioBid.objects.filter(
                ScenarioSystemNumber__AnalyzerPacketSystemNumber=analyzer_packet_system_number
            ).values(
                'ScenarioSystemNumber',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber',
                'AnalyzerBidName'
            )
            log_debug("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"Query : {str(bid_info.query)}")
            scee_bid = TScenario.objects.filter(AnalyzerPacketSystemNumber=analyzer_packet_system_number).values('ScenarioName', 'ScenarioSystemNumber', 'SummaryGeneratedIndicator', 'ScenarioNumber')
            log_debug("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"Query : {str(scee_bid.query)}")
            if not scee_bid:
                log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"No scenarios found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No scenario found for given scenario system number"}, status=status.HTTP_400_BAD_REQUEST)
            scee_bid_df = pd.DataFrame(scee_bid)
            if not bid_info:
                log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"No bids found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"error": "No bids found for given scenario"}, status=status.HTTP_400_BAD_REQUEST)
            bid_df = pd.DataFrame(bid_info)
            bid_df.rename(columns={
                'ScenarioSystemNumber__ScenarioName': 'ScenarioName',
                'ScenarioSystemNumber__ScenarioNumber': 'ScenarioNumber',
                'ScenarioSystemNumber__SummaryGeneratedIndicator': 'SummaryGeneratedIndicator',
                'PricingProfileSummarySystemNumber__SourceIncentivePlanBidNumber': 'BidNumber'
            }, inplace=True)
            scee_bid_df['TempScenarioNumber'] = scee_bid_df.apply(
                lambda r: getScenarioHierarchy(r['ScenarioSystemNumber']) if not r['SummaryGeneratedIndicator'] else str(r['ScenarioNumber']),
                axis=1
            )
            merged_df = pd.merge(scee_bid_df[['ScenarioSystemNumber', 'TempScenarioNumber', 'ScenarioName']], bid_df, on=['ScenarioSystemNumber'], how='inner')
            if merged_df.empty:
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"No scenario-bid mapping data found for AnalyzerPacketSystemNumber: {analyzer_packet_system_number}")
                log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
                return Response({"message": "No data found for the selected scenarios"}, status=status.HTTP_200_OK)
            merged_df.loc[merged_df['BidNumber'].astype(str).str.startswith('99'), 'AnalyzerBidName'] = 'Unincented PLD'
            final_json = {"Scenario": []}
            merged_df = merged_df.astype(str)
            for scenario, df_scn in merged_df.groupby("ScenarioSystemNumber"):
                scenario_block = {
                    "ScenarioSystemNumber": str(scenario),
                    "ScenarioName": df_scn["ScenarioName"].iloc[0],
                    "Bid": []
                }
                for _, row in df_scn.iterrows():
                    if str(row["BidNumber"]).startswith('999'):
                        bidname = "Unincented PLD"
                    else:
                        bidname = row['AnalyzerBidName']
                    scenario_block["Bid"].append({
                        "BidNumber": row["BidNumber"],
                        "BidName": bidname
                    })
                final_json["Scenario"].append(scenario_block)
            log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            return Response(final_json, status=status.HTTP_200_OK)
        except Exception as e:
            import traceback
            print(traceback.print_exc())
            log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"Exception occurred: {str(e)}")
            log_info("Shipping Profile Filters API Filter1 NoBQ GET Method", context="Shipping Profile Filters API Filter1 NoBQ GET Method Ended", trans_tm=int((time.time() - start_time) * 1000))
            log_error("Shipping Profile Filters API Filter1 NoBQ GET Method", context=f"Stack Trace: {str(traceback.format_exc())}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
